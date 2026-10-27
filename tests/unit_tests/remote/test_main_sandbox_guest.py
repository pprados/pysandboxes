# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`run_guest` and its helpers: the exit code and the output markers the host reads from the QEMU guest."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import main_sandbox
from pysandboxes.remote.daemon_parameters import DaemonParameters
from pysandboxes.remote.qemu_guest_console_io import PYTHON_OUTPUT_END, PYTHON_OUTPUT_START


class _Stream:
    """A text stream that logs what is written and flushed, in order, into a shared journal."""

    def __init__(self, name: str, journal: list[str]) -> None:
        self.name = name
        self.journal = journal

    def write(self, text: str) -> int:
        if text.strip():
            self.journal.append(f"{self.name}:{text.strip()}")
        return len(text)

    def flush(self) -> None:
        self.journal.append(f"{self.name}:flush")


def _config(run_dir: Path | str | None, *, args: tuple[str, ...] = (), **params: str) -> DaemonParameters:
    return DaemonParameters(
        all_rules=EmptyRules._replace(os_sandbox_params=params),  # type: ignore[arg-type]
        log_level=logging.INFO,
        log_format="%(message)s",
        use_rich_handler=False,
        token="tok",
        port=1234,
        init_fn="",
        python_main_args=args,
        guest_run_dir=None if run_dir is None else str(run_dir),
    )


class TestBootConsoleKnob:
    @pytest.mark.parametrize("raw", ["true", "TRUE", " yes ", "1"])
    def test_truthy_spellings_turn_it_on(self, raw: str) -> None:
        rules = SimpleNamespace(os_sandbox_params={"show_boot_console": raw})

        assert main_sandbox._qemu_show_boot_console_truthy_from_rules(rules) is True

    @pytest.mark.parametrize("raw", ["false", "0", "no", "", "maybe"])
    def test_anything_else_leaves_it_off(self, raw: str) -> None:
        rules = SimpleNamespace(os_sandbox_params={"show_boot_console": raw})

        assert main_sandbox._qemu_show_boot_console_truthy_from_rules(rules) is False

    @pytest.mark.parametrize("rules", [None, SimpleNamespace(), SimpleNamespace(os_sandbox_params={})])
    def test_missing_rules_or_params_leave_it_off(self, rules: Any) -> None:
        assert main_sandbox._qemu_show_boot_console_truthy_from_rules(rules) is False

    def test_an_absent_key_defaults_to_off(self) -> None:
        rules = SimpleNamespace(os_sandbox_params={"other": "true"})

        assert main_sandbox._qemu_show_boot_console_truthy_from_rules(rules) is False

    def test_the_trace_needs_both_a_run_dir_and_the_knob(self, tmp_path: Path) -> None:
        assert main_sandbox._qemu_show_boot_console_guest_trace_enabled(_config(tmp_path, show_boot_console="true"))
        assert not main_sandbox._qemu_show_boot_console_guest_trace_enabled(_config(None, show_boot_console="true"))
        assert not main_sandbox._qemu_show_boot_console_guest_trace_enabled(_config(tmp_path))

    def test_the_trace_is_flushed_at_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        journal: list[str] = []
        monkeypatch.setattr("sys.stderr", _Stream("err", journal))

        main_sandbox._qemu_show_boot_console_guest_trace(_config(tmp_path, show_boot_console="true"), "loud")

        assert journal == ["err:[PYSANDBOX_DIAG] loud", "err:flush"]

    def test_the_trace_goes_to_stderr_only_when_enabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main_sandbox._qemu_show_boot_console_guest_trace(_config(tmp_path), "quiet")
        main_sandbox._qemu_show_boot_console_guest_trace(_config(tmp_path, show_boot_console="true"), "loud")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "[PYSANDBOX_DIAG] loud\n"


class TestRunGuest:
    @pytest.fixture
    def guest(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Stub the process-wide setup `run_guest` performs; return the order in which stderr is handled."""
        order: list[str] = []
        monkeypatch.setattr("pysandboxes.main_logger.config_log", lambda *a, **k: None)
        monkeypatch.setattr("pysandboxes.learning.set_learning_path", lambda path: None)

        def redirect(run_dir: str | None) -> int:
            order.append("redirect")
            return 7

        monkeypatch.setattr(main_sandbox, "_redirect_guest_stderr", redirect)
        monkeypatch.setattr(main_sandbox, "_restore_guest_stderr", lambda fd: order.append(f"restore{fd}"))
        monkeypatch.delenv("OS_SANDBOX", raising=False)
        return order

    def _python(self, monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[Any]:
        calls: list[Any] = []

        def python_in_sb(all_rules: Any, args: list[str], module_specs: Any = None) -> int:
            calls.append((args, module_specs))
            if isinstance(outcome, BaseException):
                raise outcome
            return int(outcome)

        monkeypatch.setattr("pysandboxes.remote.python_in_sb.python_in_sb", python_in_sb)
        return calls

    def test_a_program_exit_code_is_returned_and_written(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls = self._python(monkeypatch, 3)

        rc = main_sandbox.run_guest(_config(tmp_path, args=("-m", "mod")))

        assert rc == 3
        assert calls == [(["-m", "mod"], None)]
        assert (tmp_path / "exitcode").read_text() == "3"
        assert capsys.readouterr().out == f"{PYTHON_OUTPUT_START}\n{PYTHON_OUTPUT_END}\n"

    def test_the_markers_are_flushed_around_the_redirect(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        journal: list[str] = []
        monkeypatch.setattr("sys.stdout", _Stream("out", journal))
        monkeypatch.setattr(main_sandbox, "_redirect_guest_stderr", lambda run_dir: journal.append("redirect"))
        monkeypatch.setattr(main_sandbox, "_restore_guest_stderr", lambda fd: journal.append("restore"))
        self._python(monkeypatch, 0)

        main_sandbox.run_guest(_config(tmp_path, args=("x.py",)))

        assert journal == [
            f"out:{PYTHON_OUTPUT_START}",
            "out:flush",
            "redirect",
            "restore",
            f"out:{PYTHON_OUTPUT_END}",
            "out:flush",
        ]

    def test_the_guest_runs_its_own_daemon_as_a_subprocess_provider(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._python(monkeypatch, 0)

        main_sandbox.run_guest(_config(tmp_path, args=("x.py",)))

        import os

        assert os.environ["OS_SANDBOX"] == "subprocess"
        monkeypatch.delenv("OS_SANDBOX")

    def test_stderr_is_redirected_around_the_program_and_restored_before_the_end_marker(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._python(monkeypatch, 0)

        main_sandbox.run_guest(_config(tmp_path, args=("x.py",)))

        assert guest == ["redirect", "restore7"]

    def test_a_failing_program_is_reported_while_the_redirect_holds_then_fails_the_run(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._python(monkeypatch, RuntimeError("program failed"))

        with pytest.raises(RuntimeError, match="program failed"):
            main_sandbox.run_guest(_config(tmp_path, args=("x.py",)))

        assert (tmp_path / "exitcode").read_text() == "1"
        captured = capsys.readouterr()
        assert "RuntimeError: program failed" in captured.err
        assert captured.out.endswith(f"{PYTHON_OUTPUT_END}\n")
        assert guest == ["redirect", "restore7"]

    @pytest.mark.parametrize(("raised", "code"), [(SystemExit(5), "5"), (SystemExit(0), "0"), (SystemExit(None), "0")])
    def test_a_sys_exit_is_recorded_and_propagated(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raised: SystemExit, code: str
    ) -> None:
        self._python(monkeypatch, raised)

        with pytest.raises(SystemExit):
            main_sandbox.run_guest(_config(tmp_path, args=("x.py",)))

        assert (tmp_path / "exitcode").read_text() == code

    def test_without_a_program_the_server_runs_and_its_status_is_written(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def run_server(process_config: Any) -> int:
            return 0

        monkeypatch.setattr(main_sandbox, "run_server", run_server)

        assert main_sandbox.run_guest(_config(tmp_path)) == 0
        assert (tmp_path / "exitcode").read_text() == "0"
        assert guest == []

    def test_a_server_that_crashes_writes_a_failure_status(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def run_server(process_config: Any) -> int:
            raise OSError("bind failed")

        monkeypatch.setattr(main_sandbox, "run_server", run_server)

        with pytest.raises(OSError, match="bind failed"):
            main_sandbox.run_guest(_config(tmp_path))

        assert (tmp_path / "exitcode").read_text() == "1"

    def test_without_a_run_dir_the_missing_exit_code_is_logged(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._python(monkeypatch, 0)

        with caplog.at_level(logging.WARNING, logger="pysandboxes.remote.main_sandbox"):
            assert main_sandbox.run_guest(_config(None, args=("x.py",))) == 0

        assert "guest_run_dir missing; cannot write exitcode 0" in caplog.text

    def test_an_unwritable_run_dir_is_logged_and_does_not_hide_the_result(
        self, guest: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._python(monkeypatch, 4)

        with caplog.at_level(logging.WARNING, logger="pysandboxes.remote.main_sandbox"):
            rc = main_sandbox.run_guest(_config(tmp_path / "gone", args=("x.py",)))

        assert rc == 4
        assert "failed to write exitcode" in caplog.text
