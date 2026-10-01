# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for the ``python-sb`` CLI entry point (:mod:`pysandboxes.python_sb`).

Integration tests run ``python -m pysandboxes.python_sb`` as a subprocess, which leaves
``main()`` itself almost uncovered in-process. These tests exercise its argument/config
resolution, its branch dispatch (``--version``, config errors, ``none``/subprocess/VM
providers) and its environment-building logic directly, with the sandbox launcher and
the OS provider it drives replaced by fakes so no real sandbox is ever started.
"""

import logging
import sys
import types
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

import pysandboxes.python_sb as python_sb
from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.remote.none_daemon import NoneDaemon
from pysandboxes.remote.qemu_guest_console_io import GUEST_STDERR_FILE
from pysandboxes.remote.vm_sse_daemon import VMSSEDaemon
from pysandboxes.sb_types import Envs


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``main()`` probes ``~/.ipython``; pin HOME (and Windows' USERPROFILE) so it is deterministic."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _config_path(tmp_path: Path) -> Path:
    """A real (empty) config file on disk, even though the loader is stubbed below."""
    path = tmp_path / ".py-sandboxes"
    path.write_text("")
    return path


def _patch_cmd_line(
    monkeypatch: pytest.MonkeyPatch,
    *,
    python_parsed_args: list[str],
    sandboxes_args: list[str],
    python_cmd: list[str],
    config_path: Path,
) -> None:
    """Replace ``parse_python_cmd_line`` with one returning the given, fixed, dispatch tuple."""
    monkeypatch.setattr(
        python_sb,
        "parse_python_cmd_line",
        lambda argv: (python_parsed_args, sandboxes_args, python_cmd, config_path),
    )


def _stub_config_loader(
    monkeypatch: pytest.MonkeyPatch,
    all_rules: AllRules,
    captured: dict[str, Any] | None = None,
) -> None:
    """Replace ``load_and_parse_config`` and optionally record how it was called."""

    def _fake(config_path: Path, *, envs: Any, **extra_rules: Any) -> AllRules:
        if captured is not None:
            captured["config_path"] = config_path
            captured["envs"] = envs
            captured["extra_rules"] = extra_rules
        return all_rules

    monkeypatch.setattr(python_sb, "load_and_parse_config", _fake)


def _stub_providers_factory(monkeypatch: pytest.MonkeyPatch, name: str, factory: Callable[..., Any]) -> None:
    """Replace the OS-provider registry with a single-entry mapping to ``factory``."""
    monkeypatch.setattr(python_sb, "providers_factory", {name: factory})


class TestGetTerminalSize:
    """``_get_terminal_size`` must never raise, whatever the environment looks like."""

    def test_uses_the_real_terminal_size_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        size = type("Size", (), {"columns": 132, "lines": 43})()
        # `os.get_terminal_size` is a single process-wide function that pytest's own terminal
        # reporter also calls between test phases: accept arbitrary args so that in-flight call
        # gets the fake size back instead of a TypeError that would crash the test run.
        monkeypatch.setattr(python_sb.os, "get_terminal_size", lambda *a, **k: size)

        assert python_sb._get_terminal_size() == (132, 43)

    def test_falls_back_to_columns_and_lines_env_vars_when_not_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise OSError("not a tty")

        monkeypatch.setattr(python_sb.os, "get_terminal_size", _raise)
        monkeypatch.setenv("COLUMNS", "100")
        monkeypatch.setenv("LINES", "50")

        assert python_sb._get_terminal_size() == (100, 50)

    def test_falls_back_to_defaults_when_env_vars_are_not_numeric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise OSError("not a tty")

        monkeypatch.setattr(python_sb.os, "get_terminal_size", _raise)
        monkeypatch.setenv("COLUMNS", "not-a-number")
        monkeypatch.delenv("LINES", raising=False)

        assert python_sb._get_terminal_size() == (python_sb._DEFAULT_COLUMNS, python_sb._DEFAULT_LINES)


class TestDebugLog:
    """``_debug_log`` wires up the verbose logging ``python-sb`` uses under ``DEBUG=1``."""

    def test_configures_loggers_at_the_expected_levels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config_log_mock = MagicMock()
        monkeypatch.setattr(python_sb, "config_log", config_log_mock)
        saved_levels = {
            name: logging.getLogger(name).level
            for name in ("asyncio", "uvicorn", "uvicorn.error", "pysandboxes", "pysandboxes.remote.firejail_daemon")
        }
        try:
            python_sb._debug_log()

            config_log_mock.assert_called_once_with(logging.DEBUG)
            assert logging.getLogger("asyncio").level == logging.WARNING
            assert logging.getLogger("uvicorn").level == logging.ERROR
            assert logging.getLogger("pysandboxes").level == logging.DEBUG
            assert logging.getLogger("pysandboxes.remote.firejail_daemon").level == logging.DEBUG
        finally:
            for name, level in saved_levels.items():
                logging.getLogger(name).setLevel(level)


class TestMainEarlyExits:
    """Branches of ``main()`` that never reach the sandbox launcher."""

    def test_version_flag_prints_python_version_and_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=["--version"],
            sandboxes_args=[],
            python_cmd=[],
            config_path=_config_path(tmp_path),
        )
        _stub_config_loader(monkeypatch, EmptyRules._replace(os_sandbox="fake-version"))
        _stub_providers_factory(monkeypatch, "fake-version", lambda token, python_args: MagicMock())

        with pytest.raises(SystemExit) as exc_info:
            python_sb.main()

        assert exc_info.value.code == 0
        expected = "Python " + ".".join(map(str, sys.version_info[0:3]))
        assert capsys.readouterr().out.strip() == expected

    def test_config_syntax_error_prints_to_stderr_and_exits_minus_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )

        def _raise_syntax_error(config_path: Path, *, envs: Any, **extra_rules: Any) -> AllRules:
            raise ConfigSyntaxError("bad rule", ["line 3: unknown key"])

        monkeypatch.setattr(python_sb, "load_and_parse_config", _raise_syntax_error)

        with pytest.raises(SystemExit) as exc_info:
            python_sb.main()

        assert exc_info.value.code == -1
        err = capsys.readouterr().err
        assert "bad rule" in err
        assert "line 3: unknown key" in err

    def test_sandboxes_args_and_term_rule_reach_the_config_loader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``main()`` must translate CLI ``--key=value`` args and always request ``$TERM``."""
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=["--expose-ro=/x"],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )
        captured: dict[str, Any] = {}

        def _stop(config_path: Path, *, envs: Any, **extra_rules: Any) -> AllRules:
            captured["config_path"] = config_path
            captured["envs"] = envs
            captured["extra_rules"] = extra_rules
            raise ConfigSyntaxError("stop-here", [])

        monkeypatch.setattr(python_sb, "load_and_parse_config", _stop)

        with pytest.raises(SystemExit):
            python_sb.main()

        assert captured["envs"] is python_sb.os.environ
        assert captured["extra_rules"]["expose-ro"] == {"/x"}
        assert captured["extra_rules"]["env"] == {"TERM=${TERM}"}

    def test_ipython_dir_adds_an_expose_rw_rule(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A stub module, not a reliance on IPython actually being installed in this venv.
        monkeypatch.setitem(sys.modules, "IPython", types.ModuleType("IPython"))
        (tmp_path / ".ipython").mkdir()
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )
        captured: dict[str, Any] = {}

        def _stop(config_path: Path, *, envs: Any, **extra_rules: Any) -> AllRules:
            captured["extra_rules"] = extra_rules
            raise ConfigSyntaxError("stop-here", [])

        monkeypatch.setattr(python_sb, "load_and_parse_config", _stop)

        with pytest.raises(SystemExit):
            python_sb.main()

        assert "~/.ipython" in captured["extra_rules"]["expose-rw"]

    def test_ipython_import_error_is_silently_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ipython").mkdir()
        monkeypatch.setitem(sys.modules, "IPython", None)
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )
        captured: dict[str, Any] = {}

        def _stop(config_path: Path, *, envs: Any, **extra_rules: Any) -> AllRules:
            captured["extra_rules"] = extra_rules
            raise ConfigSyntaxError("stop-here", [])

        monkeypatch.setattr(python_sb, "load_and_parse_config", _stop)

        with pytest.raises(SystemExit):
            python_sb.main()

        assert "expose-rw" not in captured["extra_rules"]


class TestMainNoneDaemon:
    """The ``none`` provider runs in-process: ``main()`` must delegate, not launch anything."""

    def test_delegates_to_python_in_sb_after_entering_the_sandbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        python_cmd = ["-c", "print('hi')"]
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=python_cmd,
            config_path=_config_path(tmp_path),
        )
        all_rules = EmptyRules._replace(os_sandbox="none")
        _stub_config_loader(monkeypatch, all_rules)
        _stub_providers_factory(
            monkeypatch, "none", lambda token, python_args: NoneDaemon(token, python_args=python_args)
        )
        enter_mock = MagicMock()
        monkeypatch.setattr("pysandboxes.lifecycle.enter", enter_mock)
        python_in_sb_mock = MagicMock(return_value=99)
        monkeypatch.setattr("pysandboxes.remote.python_in_sb.python_in_sb", python_in_sb_mock)

        result = python_sb.main()

        assert result == 99
        enter_mock.assert_called_once_with()
        python_in_sb_mock.assert_called_once_with(all_rules, python_cmd)


class _FakeSubprocessDaemon:
    """Duck-typed stand-in for a subprocess-family daemon (neither ``NoneDaemon`` nor a VM)."""

    def __init__(self) -> None:
        self.port = 4242
        self.on_process_launched: Callable[[int], None] | None = None
        self.subprocess_cmd_calls: list[tuple[Any, Any, Path, Path, bool]] = []
        self.kill_slirp_calls = 0

    def subprocess_cmd(
        self, all_rules: Any, *, envs: Any, pipe_path: Path, temp: Path
    ) -> tuple[list[str], dict[str, str]]:
        self.subprocess_cmd_calls.append((all_rules, envs, pipe_path, temp, temp.is_dir()))
        return (["fake-launcher"], {"FAKE_EXTRA": "1"})

    def get_launch_extras(self) -> tuple[None, tuple[int, ...]]:
        return (None, ())

    def _kill_slirp(self) -> None:
        self.kill_slirp_calls += 1


class _FakeProcess:
    """Stand-in for the ``asyncio.subprocess.Process`` returned by the mocked ``launch_sandbox``."""

    def __init__(self, rc: int) -> None:
        self._rc = rc
        self.stdout: Any = None
        self.stderr: Any = None

    async def wait(self) -> int:
        return self._rc


class TestMainSubprocessBranch:
    """Non-VM providers: ``main()`` builds the env, the argv, and awaits the launcher."""

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        daemon: _FakeSubprocessDaemon,
        all_rules: AllRules,
        rc: int,
        python_cmd: list[str],
    ) -> tuple[int, MagicMock]:
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=python_cmd,
            config_path=_config_path(tmp_path),
        )
        _stub_config_loader(monkeypatch, all_rules)
        _stub_providers_factory(monkeypatch, all_rules.os_sandbox, lambda token, python_args: daemon)
        launch_sandbox_mock = AsyncMock(return_value=_FakeProcess(rc))
        monkeypatch.setattr(python_sb, "launch_sandbox", launch_sandbox_mock)

        result = python_sb.main()
        return result, launch_sandbox_mock

    def test_happy_path_builds_argv_env_and_returns_process_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PY_SB_TEST_MARKER", "from-os-environ")
        daemon = _FakeSubprocessDaemon()
        all_rules = EmptyRules._replace(os_sandbox="fake-sub", port=4321, envs=Envs({"FOO": "bar"}), learn=False)
        python_cmd = ["-c", "print(1)"]

        result, launch_sandbox_mock = self._run(
            tmp_path, monkeypatch, daemon=daemon, all_rules=all_rules, rc=7, python_cmd=python_cmd
        )

        assert result == 7
        assert len(daemon.subprocess_cmd_calls) == 1
        _, _, pipe_path, temp, existed_during_call = daemon.subprocess_cmd_calls[0]
        assert existed_during_call
        assert not temp.exists(), "the run's temp dir must be cleaned up once main() returns"

        launch_sandbox_mock.assert_awaited_once()
        call = launch_sandbox_mock.await_args
        cmd, called_pipe_path = call.args
        assert cmd == ["fake-launcher", "-c", "print(1)", "--_named-pipe", str(pipe_path), "--_python-sb"]
        assert called_pipe_path == pipe_path
        env = call.kwargs["envs"]
        assert env["FOO"] == "bar"
        assert env["FAKE_EXTRA"] == "1"
        assert "PY_SB_TEST_MARKER" not in env, "learn=False must not merge the host's os.environ"
        assert call.kwargs["pass_fds"] == ()
        assert call.kwargs["on_launched"] is daemon.on_process_launched
        assert daemon.kill_slirp_calls == 1

    def test_learn_mode_merges_the_host_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PY_SB_TEST_MARKER", "from-os-environ")
        daemon = _FakeSubprocessDaemon()
        all_rules = EmptyRules._replace(os_sandbox="fake-sub-learn", port=4321, envs=Envs({}), learn=True)

        result, launch_sandbox_mock = self._run(
            tmp_path, monkeypatch, daemon=daemon, all_rules=all_rules, rc=0, python_cmd=["-c", "print(1)"]
        )

        assert result == 0
        env = launch_sandbox_mock.await_args.kwargs["envs"]
        assert env["PY_SB_TEST_MARKER"] == "from-os-environ"


class _FakeDaemonWithLaunchParamsOverride(_FakeSubprocessDaemon):
    """Exercises the ``get_launch_params_for_python_sb`` override path."""

    def __init__(self) -> None:
        super().__init__()
        self.custom_process_config = object()
        self.custom_on_launched: Callable[[int], None] = lambda pid: None
        self.launch_params_calls: list[tuple[Any, ...]] = []

    def get_launch_params_for_python_sb(
        self, all_rules: Any, log_level: int, token: str, init_fn: str, pipe_path: Path, temp: Path
    ) -> dict[str, Any]:
        self.launch_params_calls.append((all_rules, log_level, token, init_fn, pipe_path, temp))
        return {
            "pass_fds": (99,),
            "on_launched": self.custom_on_launched,
            "process_config": self.custom_process_config,
        }


class TestMainSubprocessBranchLaunchParamsOverride:
    """A provider's ``get_launch_params_for_python_sb`` overrides the launcher's defaults."""

    def test_provider_supplied_launch_params_override_the_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        daemon = _FakeDaemonWithLaunchParamsOverride()
        all_rules = EmptyRules._replace(os_sandbox="fake-sub-override", port=1234, envs=Envs({}), learn=False)
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )
        _stub_config_loader(monkeypatch, all_rules)
        _stub_providers_factory(monkeypatch, "fake-sub-override", lambda token, python_args: daemon)
        launch_sandbox_mock = AsyncMock(return_value=_FakeProcess(0))
        monkeypatch.setattr(python_sb, "launch_sandbox", launch_sandbox_mock)

        python_sb.main()

        assert len(daemon.launch_params_calls) == 1
        call = launch_sandbox_mock.await_args
        assert call is not None
        assert call.kwargs["pass_fds"] == (99,)
        assert call.kwargs["on_launched"] is daemon.custom_on_launched
        assert call.kwargs["process_config"] is daemon.custom_process_config


class TestMainVMBranch:
    """VM-based providers (e.g. QEMU): boot media, guest env, and the exit-code precedence."""

    def _make_vm(
        self,
        *,
        subprocess_cmd_return: tuple[list[str], dict[str, str]],
        show_boot: bool,
        guest_rc: int | None,
        stdout: Any,
        stderr: Any,
        wait_process_and_filter_console_rc: int = 0,
        process_wait_rc: int = 0,
    ) -> MagicMock:
        vm = MagicMock(spec=VMSSEDaemon)
        vm.host_run_temp_prefix = "pysb-vm-test-"
        vm.port = -1
        vm.on_process_launched = None
        vm.get_launch_extras.return_value = (None, ())
        vm.subprocess_cmd.return_value = subprocess_cmd_return
        vm.augment_rules_for_guest_run_mount.side_effect = lambda rules: rules
        vm.guest_run_dir_mount.return_value = "/mnt/guest-run"
        vm.show_boot_console_truthy.return_value = show_boot
        vm.read_guest_exitcode.return_value = guest_rc
        vm.wait_process_and_filter_console = AsyncMock(return_value=wait_process_and_filter_console_rc)
        vm._kill_slirp = MagicMock()
        process = MagicMock()
        process.stdout = stdout
        process.stderr = stderr
        process.wait = AsyncMock(return_value=process_wait_rc)
        vm._process = process
        return vm

    def _run_main(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        vm: MagicMock,
        all_rules: AllRules,
    ) -> tuple[int, MagicMock]:
        _patch_cmd_line(
            monkeypatch,
            python_parsed_args=[],
            sandboxes_args=[],
            python_cmd=["-c", "print(1)"],
            config_path=_config_path(tmp_path),
        )
        _stub_config_loader(monkeypatch, all_rules)
        _stub_providers_factory(monkeypatch, all_rules.os_sandbox, lambda token, python_args: vm)
        monkeypatch.setattr(python_sb, "_get_terminal_size", lambda: (111, 22))
        launch_sandbox_mock = AsyncMock(return_value=vm._process)
        monkeypatch.setattr(python_sb, "launch_sandbox", launch_sandbox_mock)

        result = python_sb.main()
        return result, launch_sandbox_mock

    def test_no_guest_exitcode_and_zero_qemu_wait_is_treated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vm = self._make_vm(
            subprocess_cmd_return=(["qemu-fake"], {"X": "1"}),
            show_boot=False,
            guest_rc=None,
            stdout=None,
            stderr=None,
        )
        all_rules = EmptyRules._replace(os_sandbox="fake-vm", port=5678, envs=Envs({"FOO": "bar"}), learn=False)

        result, launch_sandbox_mock = self._run_main(tmp_path, monkeypatch, vm=vm, all_rules=all_rules)

        assert result == 1
        vm._kill_slirp.assert_called_once_with()
        launch_sandbox_mock.assert_awaited_once()
        call = launch_sandbox_mock.await_args
        assert call.kwargs["cmd"] == ["qemu-fake"]
        env = call.kwargs["envs"]
        assert env["FOO"] == "bar"
        assert env["X"] == "1"
        assert Path(env["TMPDIR"]).name.startswith("pysb-vm-test-")
        assert not Path(env["TMPDIR"]).exists(), "the run's temp dir must be cleaned up once main() returns"

        guest_rules = vm.augment_rules_for_guest_run_mount.call_args.args[0]
        assert guest_rules.envs["COLUMNS"] == "111"
        assert guest_rules.envs["LINES"] == "22"
        # subprocess_cmd is called with the *original* rules, not the guest-augmented ones.
        original_rules = vm.subprocess_cmd.call_args.args[0]
        assert "COLUMNS" not in original_rules.envs

    def test_guest_exitcode_wins_over_qemu_wait_status_via_filter_console(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vm = self._make_vm(
            subprocess_cmd_return=(["qemu-fake"], {}),
            show_boot=True,
            guest_rc=5,
            stdout=MagicMock(),
            stderr=MagicMock(),
            wait_process_and_filter_console_rc=0,
        )
        all_rules = EmptyRules._replace(os_sandbox="fake-vm-boot", port=5679, envs=Envs({}), learn=False)
        monkeypatch.chdir(tmp_path)

        result, launch_sandbox_mock = self._run_main(tmp_path, monkeypatch, vm=vm, all_rules=all_rules)

        assert result == 5
        vm.wait_process_and_filter_console.assert_awaited_once()
        filter_call = vm.wait_process_and_filter_console.await_args
        assert filter_call.kwargs["forward_all"] is True
        assert (tmp_path / python_sb.QEMU_CONSOLE_LOG_NAME).exists()

    def test_qemu_wait_status_is_used_when_no_guest_exitcode_and_wait_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Neither the guest exitcode file nor a clean (zero) hypervisor wait: trust the wait status."""
        vm = self._make_vm(
            subprocess_cmd_return=(["qemu-fake"], {}),
            show_boot=False,
            guest_rc=None,
            stdout=None,
            stderr=None,
            process_wait_rc=7,
        )
        all_rules = EmptyRules._replace(os_sandbox="fake-vm-wait-status", port=5681, envs=Envs({}), learn=False)

        result, _ = self._run_main(tmp_path, monkeypatch, vm=vm, all_rules=all_rules)

        assert result == 7

    def test_guest_stderr_tail_reads_from_the_shared_run_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: python_sb must tail ``<tmp>/GUEST_STDERR_FILE``, not the pipe path."""
        seen_paths: list[Path] = []
        real_tail = python_sb.GuestStderrTail

        class _RecordingTail(real_tail):  # type: ignore[misc,valid-type]
            def __init__(self, path: Path, **kwargs: Any) -> None:
                seen_paths.append(path)
                super().__init__(path, **kwargs)

        monkeypatch.setattr(python_sb, "GuestStderrTail", _RecordingTail)
        vm = self._make_vm(
            subprocess_cmd_return=(["qemu-fake"], {}),
            show_boot=False,
            guest_rc=0,
            stdout=None,
            stderr=None,
        )
        all_rules = EmptyRules._replace(os_sandbox="fake-vm-tail", port=5680, envs=Envs({}), learn=False)

        self._run_main(tmp_path, monkeypatch, vm=vm, all_rules=all_rules)

        assert len(seen_paths) == 1
        assert seen_paths[0].name == GUEST_STDERR_FILE
