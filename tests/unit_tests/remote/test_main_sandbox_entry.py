# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`main_sandbox.main`: which mode the sandbox process enters, and what it prepares before arming the guards."""

import logging
import os
import pickle
import sys
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

import pysandboxes
from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.remote import main_sandbox
from pysandboxes.remote.daemon_parameters import DaemonParameters
from pysandboxes.sb_types import Envs


class _Harness:
    def __init__(self) -> None:
        self.journal: list[tuple[str, Any]] = []
        self.environ: dict[str, str] = {}

    def note(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            self.journal.append((name, (args, kwargs)))
            return None

        return record

    def named(self, name: str) -> list[Any]:
        return [entry for key, entry in self.journal if key == name]

    def order(self) -> list[str]:
        return [key for key, _ in self.journal]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    h = _Harness()
    root = logging.getLogger()
    handlers = list(root.handlers)
    monkeypatch.setattr(os, "environ", h.environ)
    monkeypatch.setattr(main_sandbox, "DEBUG", False)
    monkeypatch.setattr(main_sandbox, "_apply_netfilter", h.note("netfilter"))
    monkeypatch.setattr("pysandboxes.main_logger.config_log", h.note("config_log"))
    monkeypatch.setattr("pysandboxes.learning.set_learning_path", h.note("learning_path"))
    monkeypatch.setattr("pysandboxes.learning.set_learning_mode", h.note("learning_mode"))
    monkeypatch.setattr("pysandboxes.tools.set_is_in_sandbox", h.note("in_sandbox"))
    monkeypatch.setattr("pysandboxes.guard_socket.set_pin_dns", h.note("pin_dns"))
    monkeypatch.setattr("pysandboxes.guard_socket.apply_pin_dns_resolution", h.note("pin_resolution"))
    monkeypatch.setattr("pysandboxes.guard_import.preimport_framework_module", h.note("preimport"))
    monkeypatch.setattr("pysandboxes.py_sandbox.activate_sandboxes", h.note("activate"))
    monkeypatch.setattr(pysandboxes, "os_sandbox", "unset", raising=False)

    def run_guest(config: DaemonParameters) -> int:
        h.journal.append(("run_guest", ((config,), {})))
        return 11

    async def run_server(config: DaemonParameters) -> int:
        h.journal.append(("run_server", ((config,), {})))
        return 7

    def python_in_sb(rules: AllRules, args: list[str]) -> int:
        h.journal.append(("python_in_sb", ((rules, args), {})))
        return 5

    monkeypatch.setattr(main_sandbox, "run_guest", run_guest)
    monkeypatch.setattr(main_sandbox, "run_server", run_server)
    monkeypatch.setattr("pysandboxes.remote.python_in_sb.python_in_sb", python_in_sb)
    yield h
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)


def _without_pytest(environ: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in environ.items() if k != "PYTEST_CURRENT_TEST"}


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rules: AllRules = EmptyRules, *argv: str, **config: Any
) -> int:
    parameters = DaemonParameters(
        all_rules=rules,
        log_level=logging.INFO,
        log_format="%(message)s",
        use_rich_handler=False,
        token="tok",
        port=1234,
        init_fn="",
        **config,
    )
    pipe = tmp_path / "config.pkl"
    pipe.write_bytes(pickle.dumps(parameters))
    monkeypatch.setattr(sys, "argv", ["main_sandbox", "--_named-pipe", f" {pipe} ", *argv])
    return main_sandbox.main()


def test_the_server_is_the_default_mode(harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _run(monkeypatch, tmp_path) == 7

    assert harness.order()[-1] == "run_server"


def test_the_guards_are_armed_before_the_sandbox_and_learning_flags_are_raised(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, tmp_path, EmptyRules._replace(learn=True))

    order = harness.order()
    assert (
        order.index("activate") < order.index("in_sandbox") < order.index("learning_mode") < order.index("run_server")
    )
    assert harness.named("in_sandbox") == [((True,), {})]
    assert harness.named("learning_mode") == [((True,), {})]
    assert order.index("preimport") < order.index("activate")
    assert harness.named("preimport") == [(("tblib",), {})]


def test_the_server_path_hands_the_environment_and_no_provider_override_to_the_guards(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness.environ["KEEP"] = "1"

    _run(monkeypatch, tmp_path)

    (args, kwargs), *_ = harness.named("activate")
    assert args == (EmptyRules, harness.environ)
    assert kwargs == {"rules_provider": None}
    assert harness.environ["KEEP"] == "1"
    assert pysandboxes.os_sandbox == EmptyRules.os_sandbox


def test_python_sb_runs_the_program_with_the_unparsed_arguments(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert _run(monkeypatch, tmp_path, EmptyRules, "--_python-sb", "script.py", "--flag") == 5

    (args, _), *_ = harness.named("python_in_sb")
    assert args == (EmptyRules, ["script.py", "--flag"])
    assert not harness.named("run_server")


def test_an_abbreviated_internal_option_is_not_taken_from_the_command_line(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert _run(monkeypatch, tmp_path, EmptyRules, "--_python", "script.py") == 7

    assert not harness.named("python_in_sb")


def test_the_netfilter_is_applied_only_when_there_are_rules(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, tmp_path)
    assert not harness.named("netfilter")

    _run(monkeypatch, tmp_path, EmptyRules, netfilter_rules=("-A INPUT -j DROP",))

    assert harness.named("netfilter") == [((("-A INPUT -j DROP",),), {})]


@pytest.mark.parametrize("pinned", [(), ("192.0.2.1",)])
def test_pinned_dns_patches_the_resolution_only_when_set(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pinned: tuple[str, ...]
) -> None:
    _run(monkeypatch, tmp_path, EmptyRules._replace(pin_dns=pinned))  # type: ignore[arg-type]

    assert harness.named("pin_dns") == [((pinned,), {})]
    assert len(harness.named("pin_resolution")) == (1 if pinned else 0)


def test_the_debug_switch_configures_the_logs(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main_sandbox, "DEBUG", True)
    monkeypatch.setattr(main_sandbox, "_debug_log", harness.note("debug_log"))

    _run(monkeypatch, tmp_path)

    assert harness.order()[0] == "debug_log"


class TestGuest:
    def _rules(self) -> AllRules:
        return EmptyRules._replace(envs=Envs({"KEPT": "1", "NONE": None, "NUM": 4}))  # type: ignore[arg-type]

    def test_a_program_in_the_vm_runs_with_the_profile_environment_only(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        harness.environ.update({"KEPT": "old", "VM_ONLY": "x", "PATH": "/bin"})

        rc = _run(monkeypatch, tmp_path, self._rules(), python_main_args=("x.py",), guest_run_dir=str(tmp_path))

        assert rc == 11
        assert _without_pytest(harness.environ) == {
            "KEPT": "1",
            "NONE": "",
            "NUM": "4",
            "TERM": "xterm-256color",
            "FORCE_COLOR": "1",
        }

    def test_a_term_chosen_by_the_profile_is_kept(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        rules = EmptyRules._replace(envs=Envs({"TERM": "dumb", "FORCE_COLOR": "0"}))

        _run(monkeypatch, tmp_path, rules, python_main_args=("x.py",), guest_run_dir=str(tmp_path))

        assert (harness.environ["TERM"], harness.environ["FORCE_COLOR"]) == ("dumb", "0")

    def test_the_rules_are_rooted_on_the_working_directory_and_the_guards_use_no_provider(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _run(monkeypatch, tmp_path, self._rules(), python_main_args=("x.py",), guest_run_dir=str(tmp_path))

        (args, kwargs), *_ = harness.named("activate")
        assert args[0].root_path == Path.cwd()
        assert kwargs == {"rules_provider": "none"}
        ((config,), _), *_ = harness.named("run_guest")
        assert config.all_rules.root_path == Path.cwd()
        assert not harness.named("run_server")

    def test_a_program_without_a_run_dir_gets_no_terminal_defaults(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _run(monkeypatch, tmp_path, self._rules(), python_main_args=("x.py",))

        assert "TERM" not in harness.environ and "FORCE_COLOR" not in harness.environ

    def test_the_vm_daemon_narrows_the_environment_but_keeps_the_rules_unrooted(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        harness.environ.update({"VM_ONLY": "x"})

        rc = _run(monkeypatch, tmp_path, self._rules(), guest_run_dir=str(tmp_path))

        assert rc == 7
        assert _without_pytest(harness.environ) == {"KEPT": "1", "NONE": "", "NUM": "4"}
        (args, kwargs), *_ = harness.named("activate")
        assert args[0].root_path == self._rules().root_path
        assert kwargs == {"rules_provider": None}


_ENTRY_POINTS = ("pysandboxes.remote.python_in_sb", "pysandboxes.remote.qemu_guest_console_io")


def _unload_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the entry points from the import system, restoring both the module table and the package attributes."""
    import pysandboxes.remote as remote_package

    for name in _ENTRY_POINTS:
        short = name.rsplit(".", 1)[1]
        monkeypatch.setattr(remote_package, short, getattr(remote_package, short), raising=False)
        monkeypatch.delitem(sys.modules, name, raising=False)


class TestEntryPointsPreloaded:
    """They must be imported before the guards are armed: afterwards, the user's import rules would deny them."""

    def _preloaded_at_activation(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str, **config: Any
    ) -> dict[str, bool]:
        _unload_entry_points(monkeypatch)
        seen: dict[str, bool] = {}

        def activate(*args: Any, **kwargs: Any) -> None:
            seen.update({name: name in sys.modules for name in _ENTRY_POINTS})
            monkeypatch.setattr("pysandboxes.remote.python_in_sb.python_in_sb", lambda rules, args: 5)

        monkeypatch.setattr("pysandboxes.py_sandbox.activate_sandboxes", activate)
        _run(monkeypatch, tmp_path, EmptyRules, *argv, **config)
        return seen

    def test_python_sb_loads_them_before_arming(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen = self._preloaded_at_activation(harness, monkeypatch, tmp_path, "--_python-sb", "x.py")

        assert seen == {name: True for name in _ENTRY_POINTS}

    def test_the_server_does_not_load_them(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen = self._preloaded_at_activation(harness, monkeypatch, tmp_path)

        assert seen == {name: False for name in _ENTRY_POINTS}


class TestGuestDiagnostics:
    def test_faulthandler_is_enabled_in_a_traced_guest(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        enabled: list[dict[str, Any]] = []
        monkeypatch.setattr("faulthandler.enable", lambda **kwargs: enabled.append(kwargs))
        rules = EmptyRules._replace(os_sandbox_params={"show_boot_console": "true"})  # type: ignore[arg-type]

        _run(monkeypatch, tmp_path, rules, guest_run_dir=str(tmp_path))

        assert enabled == [{"file": sys.stderr, "all_threads": True}]

    def test_faulthandler_is_left_alone_otherwise(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        enabled: list[dict[str, Any]] = []
        monkeypatch.setattr("faulthandler.enable", lambda **kwargs: enabled.append(kwargs))

        _run(monkeypatch, tmp_path, EmptyRules, guest_run_dir=str(tmp_path))

        assert enabled == []
