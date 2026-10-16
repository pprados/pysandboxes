# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Mutants first marked equivalent that a test can in fact tell apart: values the usual inputs never reach."""

import ipaddress
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pysandboxes import tools as api_tools
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.py_sandbox import CONFIG_NAME, _search_module_config
from pysandboxes.remote import client_subprocess_sse_daemon as client_daemon
from pysandboxes.remote import parse_cpython_args, python_in_sb
from pysandboxes.remote import qemu_sse_daemon as qemu
from pysandboxes.remote import tools as remote_tools


def _unshared(text: str) -> str:
    """A string equal to `text` but not interned: `is` tells it from `==`."""
    return "".join(list(text))


class TestDnsFamilies:
    def test_a_dns_server_of_the_other_family_is_left_out(self) -> None:
        servers: list[Any] = [ipaddress.IPv4Address("192.0.2.1"), ipaddress.IPv6Address("2001:db8::1")]

        v4 = "\n".join(rule_to_netfilter((), servers, is_ipv6=False))
        v6 = "\n".join(rule_to_netfilter((), servers, is_ipv6=True))

        assert "192.0.2.1/32" in v4 and "2001:db8::1" not in v4
        assert "2001:db8::1/128" in v6 and "192.0.2.1" not in v6


class TestCallerConfig:
    @pytest.mark.parametrize("caller", ["namedpkg.mod", "Namedpkg.mod"])
    def test_a_named_caller_keeps_its_own_package_whatever_its_spec_says(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caller: str
    ) -> None:
        site = tmp_path / "site"
        for package in ("namedpkg", "Namedpkg", "decoypkg"):
            (site / package).mkdir(parents=True)
            (site / package / "__init__.py").write_text("")
            (site / package / CONFIG_NAME).write_text("learn=false\n")
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.chdir(tmp_path)
        caller_globals: dict[str, object] = {
            "__name__": caller,
            "__spec__": SimpleNamespace(name="decoypkg.mod"),
            "search": _search_module_config,
        }

        exec("result = search(None)", caller_globals)

        assert caller_globals["result"] == site / caller.split(".")[0] / CONFIG_NAME


class TestCommandLine:
    def test_a_dash_c_program_is_not_taken_for_a_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        looked_up: list[str] = []

        def find(module: str, name: str) -> None:
            looked_up.append(module)

        monkeypatch.setattr(parse_cpython_args, "find_config_for_module", find)

        parse_cpython_args.parse_python_cmd_line(["-c", "print(1)"])

        assert looked_up == []


class TestBanner:
    def test_the_banner_names_the_os_sandbox_unless_it_is_subprocess(self, tmp_path: Path) -> None:
        rules = MagicMock(learn=False, use_py_sandbox=True, os_sandbox=_unshared("subprocess"))
        rules.learning_path = tmp_path / ".py-sandboxes"
        banners: list[str] = []

        with (
            patch.object(python_in_sb, "_before_user_code"),
            patch.object(python_in_sb, "is_learning_mode", return_value=False),
            patch.object(python_in_sb, "is_allowed", return_value=False),
            patch.object(python_in_sb.code, "interact", lambda banner, **_: banners.append(banner)),
        ):
            python_in_sb._python_interactive(rules, True)

        assert "os-sandbox=" not in banners[0]


class TestLdd:
    def test_a_signalled_ldd_yields_nothing_even_with_output(self, tmp_path: Path) -> None:
        lib = tmp_path / "libx.so"
        lib.write_text("")
        done = subprocess.CompletedProcess([], -9, stdout=f"\tlibx.so => {lib} (0x1)\n", stderr="")

        with patch.object(qemu.subprocess, "run", return_value=done):
            assert qemu._ldd_resolved_paths(Path("/bin/x")) == set()


class TestRichHandlerDetection:
    def test_the_handler_is_recognised_by_the_value_of_its_class_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler_class = type(_unshared("RichHandler"), (client_daemon.logging.Handler,), {})
        root = client_daemon.logging.getLogger()
        monkeypatch.setattr(root, "handlers", [handler_class()])

        assert client_daemon.use_rich_handler() is True


class TestApiTools:
    def test_a_line_longer_than_the_small_int_cache_is_scanned_to_its_end(self) -> None:
        line = "x" * 300

        assert api_tools._remove_comment(line) == line

    def test_only_the_missing_loop_error_is_swallowed(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("zzz unrelated failure")):
            with pytest.raises(RuntimeError, match="zzz unrelated"):
                api_tools.check_mixte_async_async()


class TestInstallHint:
    @pytest.mark.parametrize(
        ("platform_name", "marker"),
        [("".join(["dar", "win"]), "brew install"), ("".join(["win", "32"]), "winget install")],
    )
    def test_each_platform_gets_its_own_hint(
        self, monkeypatch: pytest.MonkeyPatch, platform_name: str, marker: str
    ) -> None:
        monkeypatch.setattr(sys, "platform", platform_name)

        assert marker in remote_tools.suggest_package_installation("pkg")

    @pytest.mark.parametrize("platform_name", ["aix", "zos"])
    def test_an_unknown_platform_gets_neither_hint(self, monkeypatch: pytest.MonkeyPatch, platform_name: str) -> None:
        monkeypatch.setattr(sys, "platform", platform_name)

        hint = remote_tools.suggest_package_installation("pkg")

        assert "brew install" not in hint and "winget install" not in hint


class TestPythonInSbDispatch:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
        recorded: list[tuple[str, tuple[Any, ...]]] = []

        def recorder(name: str) -> Any:
            def record(*args: Any) -> int:
                recorded.append((name, args))
                return 0

            return record

        for name in ("_python_interactive", "_python_module", "_python_command", "_python_script"):
            monkeypatch.setattr(python_in_sb, name, recorder(name))
        monkeypatch.setattr(python_in_sb, "set_learning_path", lambda path: None)
        monkeypatch.setattr(python_in_sb, "set_learning_mode", lambda learn: None)
        monkeypatch.setattr(python_in_sb, "is_learning_mode", lambda: False)
        monkeypatch.setattr(python_in_sb, "_inject_pytest_color_yes", lambda argv: recorded.append(("color", ())))
        return recorded

    def _run(self, *python_cmd: str) -> int:
        return python_in_sb.python_in_sb(MagicMock(), [_unshared(part) for part in python_cmd])

    def test_no_argument_opens_the_repl(self, calls: list[tuple[str, tuple[Any, ...]]]) -> None:
        assert self._run() == 0
        assert [name for name, _ in calls] == ["_python_interactive"]
        assert calls[0][1][1] is True

    def test_dash_m_runs_the_module_with_the_rest_as_argv(
        self, calls: list[tuple[str, tuple[Any, ...]]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["keep"])

        self._run("-m", "json.tool", "a")

        assert [(name, args[1:]) for name, args in calls] == [("_python_module", ("json.tool",))]
        assert sys.argv[1:] == ["a"] and sys.argv[0].endswith("tool.py")

    def test_dash_m_without_a_name_explains_itself(
        self, calls: list[tuple[str, tuple[Any, ...]]], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run("-m") == 0
        assert calls == []
        assert "Argument expected for -m" in capsys.readouterr().err

    def test_dash_m_pytest_asks_for_colours(self, calls: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._run("-m", "pytest", "-q")

        assert ("color", ()) in calls

    @pytest.mark.parametrize("module", ["unittest", "zlib"])
    def test_only_pytest_asks_for_colours(self, calls: list[tuple[str, tuple[Any, ...]]], module: str) -> None:
        self._run("-m", module)

        assert ("color", ()) not in calls

    def test_dash_m_of_an_unknown_module_is_refused_without_running_anything(
        self, calls: list[tuple[str, tuple[Any, ...]]], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run("-m", "no_such_module_for_python_sb", "a") == 1

        assert calls == []
        assert "No module named no_such_module_for_python_sb" in capsys.readouterr().err

    def test_dash_c_runs_the_command_and_keeps_the_other_arguments(
        self, calls: list[tuple[str, tuple[Any, ...]]]
    ) -> None:
        self._run("-c", "print(1)", "a")

        assert [(name, args[1:]) for name, args in calls] == [("_python_command", ("print(1)", ["-c", "a"]))]

    def test_dash_c_without_a_command_explains_itself(
        self, calls: list[tuple[str, tuple[Any, ...]]], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run("-c") == 0
        assert calls == []
        assert "Argument expected for -c" in capsys.readouterr().err

    def test_a_lone_dash_reads_the_program_from_stdin(
        self, calls: list[tuple[str, tuple[Any, ...]]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("print(2)"))

        self._run("-", "a")

        assert [(name, args[1:]) for name, args in calls] == [("_python_command", ("print(2)", ["-", "a"], "<stdin>"))]

    @pytest.mark.parametrize("script", ["x.py", "+x.py", "-x.py", "!x.py", "~x.py"])
    def test_anything_else_is_a_script(self, calls: list[tuple[str, tuple[Any, ...]]], script: str) -> None:
        self._run(script, "a")

        assert [(name, args[1:]) for name, args in calls] == [("_python_script", (Path(script), ["a"]))]

    @pytest.mark.parametrize("learning", [True, False])
    def test_the_learned_rules_are_saved_only_in_learning_mode(
        self, calls: list[tuple[str, tuple[Any, ...]]], monkeypatch: pytest.MonkeyPatch, learning: bool
    ) -> None:
        saved: list[bool] = []
        monkeypatch.setattr(python_in_sb, "is_learning_mode", lambda: learning)
        monkeypatch.setattr(python_in_sb, "generate_config_from_learning", lambda: saved.append(True))

        self._run("x.py")

        assert saved == ([True] if learning else [])


class TestPlatformGuards:
    @pytest.mark.parametrize("system", ["Windows", "Darwin", "AIX"])
    def test_the_linux_only_readers_refuse_other_systems(self, monkeypatch: pytest.MonkeyPatch, system: str) -> None:
        monkeypatch.setattr(remote_tools.platform, "system", lambda: system)

        with pytest.raises(AssertionError):
            remote_tools.get_systemd_resolved_upstream_dns()
        with pytest.raises(AssertionError):
            remote_tools.get_systemd_resolved_static_dns()


class TestShutdownOrder:
    def test_no_call_is_accepted_while_the_watchdog_is_being_cancelled(self) -> None:
        from unittest.mock import AsyncMock

        daemon = client_daemon.SubProcessDaemon("tok")
        daemon._accept_incoming = True
        seen: list[bool] = []

        async def cancel() -> None:
            seen.append(daemon._accept_incoming)

        async def scenario() -> None:
            with (
                patch.object(daemon, "_cancel_watchdog", cancel),
                patch.object(client_daemon.BaseSubProcessDaemon.__mro__[1], "_shutdown", AsyncMock()),
            ):
                await daemon._shutdown(True)

        import asyncio

        asyncio.run(scenario())

        assert seen == [False]


class _Ordered(set):  # type: ignore[type-arg]
    """A set that iterates in insertion order, so a `break` for a `continue` shows."""

    def __init__(self, items: list[Path]) -> None:
        super().__init__(items)
        self._items = items

    def __iter__(self) -> Any:
        return iter(self._items)


class TestQemuExecutionDirs:
    def test_a_non_file_binary_does_not_stop_the_peer_lib_search(self, tmp_path: Path) -> None:
        prefix = tmp_path / "usr"
        (prefix / "bin").mkdir(parents=True)
        (prefix / "lib").mkdir()
        (prefix / "lib" / "libpython3.so").write_text("")
        exe = prefix / "bin" / "python3"
        exe.write_bytes(b"\x7fELF")
        dirs: set[Path] = set()

        qemu._add_peer_lib_dir_for_executables(dirs, _Ordered([prefix / "bin", exe]))

        assert dirs == {(prefix / "lib").resolve()}

    def test_an_unrelated_library_does_not_stop_the_libpython_search(self, tmp_path: Path) -> None:
        exe = tmp_path / "python3"
        exe.write_bytes(b"\x7fELF")
        libdir = tmp_path / "libs"
        libdir.mkdir()
        other, libpython = libdir / "libc.so.6", libdir / "libpython3.so"
        other.write_text("")
        libpython.write_text("")
        dirs: set[Path] = set()

        with patch.object(qemu, "_ldd_resolved_paths", return_value=[other, libpython]):
            qemu._add_libpython_dirs_from_ldd(dirs, {exe})

        assert dirs == {libdir.resolve()}
