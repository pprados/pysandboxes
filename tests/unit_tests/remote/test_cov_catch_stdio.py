# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``acatch_stdio``: what a remote call returns, prints and raises, as the SSE server sees it."""

import asyncio
import contextvars
import io
import queue
import sys
from typing import Any
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import private_loop
from pysandboxes.e import SandBoxBaseExceptionError
from pysandboxes.remote import catch_stdio
from pysandboxes.remote.catch_stdio import acatch_stdio


class _Stdio:
    """Fresh context-local stdio, so no state leaks from the module import or from another test.

    It is installed only around each call: pytest swaps ``sys.stdout`` between the test phases.
    """

    def __init__(self) -> None:
        self.host = io.StringIO()
        self.stdout = catch_stdio.WrapperIO(contextvars.ContextVar("t_stdout", default=self.host))
        self.host_err = io.StringIO()
        self.stderr = catch_stdio.WrapperIO(contextvars.ContextVar("t_stderr", default=self.host_err))


@pytest.fixture
async def stdio(monkeypatch: pytest.MonkeyPatch) -> _Stdio:
    monkeypatch.setattr(private_loop, "_background_loop_ref", asyncio.get_running_loop())
    return _Stdio()


async def _call(stdio: _Stdio, q: Any, fn: Any, kwargs: dict[str, Any], *args: Any) -> dict[str, Any]:
    with patch.object(sys, "stdout", stdio.stdout), patch.object(sys, "stderr", stdio.stderr):
        # One task per call, as sse_server_daemon runs it.
        return await asyncio.create_task(acatch_stdio(q, fn, kwargs, *args))


def _shout(word: str, *, end: str = "!") -> str:
    print(word + end)
    print("warn", file=sys.stderr)
    return word.upper()


async def _ashout(word: str) -> str:
    print(word)
    return word * 2


async def test_a_sync_function_returns_its_result_and_its_output(stdio: _Stdio) -> None:
    result = await _call(stdio, None, _shout, {"end": "?"}, "hi")

    assert result == {"result": "HI", "stdout": "hi?\n", "stderr": "warn\n"}
    assert stdio.host.getvalue() == ""


async def test_an_async_function_is_awaited(stdio: _Stdio) -> None:
    result = await _call(stdio, None, _ashout, {}, "ab")

    assert result == {"result": "abab", "stdout": "ab\n", "stderr": ""}


async def test_the_async_queue_streams_the_output_before_the_result(stdio: _Stdio) -> None:
    q: asyncio.Queue = asyncio.Queue()

    await _call(stdio, q, _shout, {}, "go")

    messages = [q.get_nowait() for _ in range(q.qsize())]
    assert messages[:-1] == [{"stdout": "go!"}, {"stdout": "\n"}, {"stderr": "warn"}, {"stderr": "\n"}]
    assert messages[-1]["result"] == "GO"


async def test_a_thread_queue_gets_the_same_messages(stdio: _Stdio) -> None:
    q: queue.Queue = queue.Queue()

    await _call(stdio, q, _ashout, {}, "x")

    messages = [q.get_nowait() for _ in range(q.qsize())]
    assert messages[:-1] == [{"stdout": "x"}, {"stdout": "\n"}]
    assert messages[-1]["result"] == "xx"


async def test_an_exception_comes_back_as_the_same_object_with_its_traceback(stdio: _Stdio) -> None:
    error = ValueError("bad input")

    def fail() -> None:
        print("before")
        raise error

    q: asyncio.Queue = asyncio.Queue()
    result = await _call(stdio, q, fail, {})

    transported, traceback = result["exception"]
    assert transported is error
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "fail"
    assert result["stdout"] == "before\n"
    assert "result" not in result
    assert [m for m in (q.get_nowait() for _ in range(q.qsize())) if "exception" in m][0]["exception"][0] is error


async def test_a_system_exit_is_turned_into_a_sandbox_error_carrying_its_code(stdio: _Stdio) -> None:
    def leave() -> None:
        raise SystemExit(3)

    result = await _call(stdio, queue.Queue(), leave, {})

    transported, _ = result["exception"]
    assert type(transported) is SandBoxBaseExceptionError
    assert transported.exception_type == "builtins.SystemExit"
    assert transported.code == 3


async def test_a_non_int_exit_code_is_carried_as_its_repr(stdio: _Stdio) -> None:
    def leave() -> None:
        raise SystemExit("bye")

    result = await _call(stdio, None, leave, {})

    transported, _ = result["exception"]
    assert type(transported) is SandBoxBaseExceptionError
    assert transported.code == "'bye'"


async def test_a_keyboard_interrupt_carries_no_code(stdio: _Stdio) -> None:
    def interrupt() -> None:
        raise KeyboardInterrupt()

    result = await _call(stdio, None, interrupt, {})

    transported, _ = result["exception"]
    assert type(transported) is SandBoxBaseExceptionError
    assert transported.exception_type == "builtins.KeyboardInterrupt"
    assert transported.code is None


async def test_a_cancellation_is_not_swallowed(stdio: _Stdio) -> None:
    async def cancelled() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _call(stdio, None, cancelled, {})


async def test_the_second_call_output_is_captured_too(stdio: _Stdio) -> None:
    first = await _call(stdio, None, _ashout, {}, "one")
    second = await _call(stdio, None, _ashout, {}, "two")

    assert first["stdout"] == "one\n"
    assert second["stdout"] == "two\n"
