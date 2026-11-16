# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The order of the AppContainer launch sequence, proven with every Win32 call mocked.

``appcontainer_launcher.run`` cannot run for real off Windows, so this proves the order through
the function's own control flow rather than the real Win32 API: CreateProcess(CREATE_SUSPENDED)
must complete before the process is assigned to its Job Object, UI restrictions and the shared
socket must be in place before the thread resumes, and a failed assignment must never resume the
thread and must terminate the process and close its handles instead.
"""

import json
import socket as real_socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pysandboxes.remote import appcontainer_launcher as launcher


class _FakeListener:
    """Wraps a real local socket so bind/listen are genuine, with a non-Windows ``share``."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self._sock = real_socket.socket(real_socket.AF_INET, real_socket.SOCK_STREAM)

    def setsockopt(self, *args: Any) -> None:
        self._sock.setsockopt(*args)

    def bind(self, address: tuple[str, int]) -> None:
        self._sock.bind(address)

    def listen(self, backlog: int) -> None:
        self._sock.listen(backlog)

    def close(self) -> None:
        self._sock.close()

    def share(self, pid: int) -> bytes:
        self._calls.append("write_shared_socket")
        return b"fake-shared-socket-info"


def _fake_socket_module(calls: list[str]) -> Any:
    return SimpleNamespace(
        socket=lambda *a, **k: _FakeListener(calls),
        AF_INET=real_socket.AF_INET,
        SOCK_STREAM=real_socket.SOCK_STREAM,
        SOL_SOCKET=real_socket.SOL_SOCKET,
        SO_REUSEADDR=real_socket.SO_REUSEADDR,
        SOMAXCONN=real_socket.SOMAXCONN,
    )


def _plan(tmp_path: Path) -> Path:
    plan = {
        "profile_name": "test-profile",
        "capabilities": [],
        "grants": [],
        "port": 0,
        "child_command": ["fake.exe"],
        "shared_socket_path": str(tmp_path / "shared.bin"),
        "env": {},
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _patch_common(monkeypatch: pytest.MonkeyPatch, calls: list[str], kernel32: Any) -> None:
    """Stub every Win32-touching dependency of ``run`` that this test does not itself assert on."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launcher, "socket", _fake_socket_module(calls))
    monkeypatch.setattr(launcher, "_win_dll", lambda name: kernel32)
    monkeypatch.setattr(launcher, "_create_profile", lambda name: (object(), "S-1-package"))
    monkeypatch.setattr(launcher, "_capability_sid", lambda name: object())
    monkeypatch.setattr(launcher, "_sid_string", lambda sid: "S-1-runtime")
    monkeypatch.setattr(launcher, "_private_folder", lambda sid: "C:\\fake\\AppData")
    monkeypatch.setattr(launcher, "begin_run", lambda package_sid, name: object())
    monkeypatch.setattr(launcher, "apply_acl", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "mark_window_access", lambda sid: None)
    monkeypatch.setattr(launcher, "grant_service_window_access", lambda sid: False)
    monkeypatch.setattr(launcher, "finish_run", lambda sid: ())
    monkeypatch.setattr(launcher, "release_run_lock", lambda lock: None)
    monkeypatch.setattr(launcher, "_delete_profile", lambda name: None)
    monkeypatch.setattr(launcher, "close", lambda job: None)


def _fake_process_info() -> SimpleNamespace:
    return SimpleNamespace(dwProcessId=4321, hThread=111, hProcess=222)


def _record(calls: list[str], tag: str, result: Any = None) -> Any:
    """Return a stand-in that appends ``tag`` to ``calls`` and returns ``result``, any arguments."""

    def recorder(*args: Any, **kwargs: Any) -> Any:
        calls.append(tag)
        return result

    return recorder


class TestTheHappyPathOrder:
    def test_create_process_then_assign_then_ui_then_shared_socket_then_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        kernel32 = MagicMock(name="kernel32")
        kernel32.ResumeThread.side_effect = _record(calls, "resume_thread", 0)
        _patch_common(monkeypatch, calls, kernel32)
        monkeypatch.setattr(launcher, "_create_process", _record(calls, "create_process", _fake_process_info()))
        monkeypatch.setattr(launcher, "create_kill_on_close_job", _record(calls, "create_job", 999))
        monkeypatch.setattr(launcher, "assign", _record(calls, "assign"))
        monkeypatch.setattr(launcher, "set_ui_restrictions", _record(calls, "set_ui_restrictions"))

        exit_code = launcher.run(_plan(tmp_path), tmp_path / "config.pkl")

        assert isinstance(exit_code, int)
        assert calls == [
            "create_process",
            "create_job",
            "assign",
            "set_ui_restrictions",
            "write_shared_socket",
            "resume_thread",
        ]


class TestAFailedAssignNeverResumes:
    def test_assign_failure_terminates_the_process_and_closes_its_handles_without_resuming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        kernel32 = MagicMock(name="kernel32")
        kernel32.ResumeThread.side_effect = _record(calls, "resume_thread", 0)
        _patch_common(monkeypatch, calls, kernel32)
        monkeypatch.setattr(launcher, "_create_process", _record(calls, "create_process", _fake_process_info()))
        monkeypatch.setattr(launcher, "create_kill_on_close_job", _record(calls, "create_job", 999))

        def failing_assign(job: int, pid: int) -> None:
            calls.append("assign")
            raise OSError("AssignProcessToJobObject failed")

        monkeypatch.setattr(launcher, "assign", failing_assign)
        monkeypatch.setattr(launcher, "set_ui_restrictions", _record(calls, "set_ui_restrictions"))

        with pytest.raises(OSError, match="AssignProcessToJobObject failed"):
            launcher.run(_plan(tmp_path), tmp_path / "config.pkl")

        assert calls == ["create_process", "create_job", "assign"]
        assert "resume_thread" not in calls
        assert "set_ui_restrictions" not in calls
        assert "write_shared_socket" not in calls
        kernel32.TerminateProcess.assert_called_once_with(222, 1)
        kernel32.CloseHandle.assert_any_call(111)
        kernel32.CloseHandle.assert_any_call(222)
