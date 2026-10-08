# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A sandboxed function raising a BaseException must fail that call, nothing more.

`SystemExit(3)` escaped the child's handler and ended the sandbox process; after
a few restarts the parent watchdog ended the host application itself.
`SystemExit(0)` stopped the watchdog instead, and the next call hung until the
RPC timeout. The caller must get `SandBoxBaseExceptionError` for each such call,
from the same sandbox process, which then still answers a normal call.
"""

import os
from pathlib import Path
from typing import NoReturn

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandbox, sandboxes
from pysandboxes.e import SandBoxBaseExceptionError
from pysandboxes.remote import base_sse_daemon

config_path = Path(__file__).parent / "py-sandbox-test.profile"


class ApplicationBaseException(BaseException):
    """An application's own BaseException subclass."""


@sandbox
def sandbox_pid() -> int:
    return os.getpid()


@sandbox
def exit_with(code: int | None) -> NoReturn:
    raise SystemExit(code)


@sandbox
def interrupt() -> NoReturn:
    raise KeyboardInterrupt


@sandbox
def raise_application_base_exception() -> NoReturn:
    raise ApplicationBaseException("raised by the application")


@pytest.fixture(autouse=True)
def _short_rpc_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hang must fail the test in seconds, not after the default RPC timeout."""
    monkeypatch.setattr(base_sse_daemon, "TIMEOUT_FOR_RPC_CALL", 20)


@pytest.mark.parametrize("code", [3, 0, None])
def test_system_exit_fails_the_call_and_keeps_the_sandbox(code: int | None) -> None:
    with sandboxes(sandboxes_config=config_path):
        pid = sandbox_pid()
        for _ in range(7):
            with pytest.raises(SandBoxBaseExceptionError) as caught:
                exit_with(code)
            assert caught.value.exception_type == "builtins.SystemExit"
            assert caught.value.code == code
        assert sandbox_pid() == pid


def test_keyboard_interrupt_fails_the_call_and_keeps_the_sandbox() -> None:
    with sandboxes(sandboxes_config=config_path):
        pid = sandbox_pid()
        with pytest.raises(SandBoxBaseExceptionError) as caught:
            interrupt()
        assert caught.value.exception_type == "builtins.KeyboardInterrupt"
        assert sandbox_pid() == pid


def test_an_application_base_exception_fails_the_call_and_keeps_the_sandbox() -> None:
    with sandboxes(sandboxes_config=config_path):
        pid = sandbox_pid()
        with pytest.raises(SandBoxBaseExceptionError) as caught:
            raise_application_base_exception()
        assert caught.value.exception_type.endswith(".ApplicationBaseException")
        assert sandbox_pid() == pid


def test_system_exit_crosses_a_learned_profile(tmp_path: Path) -> None:
    """The error path must not import anything a profile learned on the happy path lacks."""
    learned = tmp_path / "learned.profile"
    bootstrap = tmp_path / "bootstrap.profile"
    bootstrap.write_text("py-sandbox=true\n" "os-sandbox=subprocess\n" f"learn={learned}\n")
    with sandboxes(sandboxes_config=bootstrap):
        sandbox_pid()
    assert learned.exists()

    with sandboxes(sandboxes_config=learned):
        pid = sandbox_pid()
        with pytest.raises(SandBoxBaseExceptionError):
            exit_with(3)
        assert sandbox_pid() == pid
