# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`sandbox_daemon`: the event stream the SSE server sends back for one remote call."""

import asyncio
import base64
import contextlib
import contextvars
import io
import json
import pickle
import sys
from typing import Any, Iterator
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import private_loop
from pysandboxes.remote import catch_stdio, sse_server_daemon
from pysandboxes.remote.sse_server_daemon import sandbox_daemon
from pysandboxes.remote.tools import from_b85


def _speak(word: str, *, end: str = "!") -> str:
    print(word + end)
    print("warn", file=sys.stderr)
    return word.upper()


async def _aspeak(word: str) -> str:
    return word * 2


def _fail() -> None:
    raise KeyError("missing key")


def _huge() -> str:
    return "x" * (10 * 1024 * 1024)


async def _forever() -> None:
    await asyncio.sleep(60)


_MODULE = __name__


@pytest.fixture(autouse=True)
async def sandbox_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(private_loop, "_background_loop_ref", asyncio.get_running_loop())


@contextlib.contextmanager
def _stdio() -> Iterator[None]:
    """Context-local stdio, installed only around a call: pytest swaps `sys.stdout` between its phases."""
    out_host, err_host = io.StringIO(), io.StringIO()
    stdout = catch_stdio.WrapperIO(contextvars.ContextVar("t_out", default=out_host))
    stderr = catch_stdio.WrapperIO(contextvars.ContextVar("t_err", default=err_host))
    with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
        yield


async def _events(function: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    with _stdio():
        stream = sandbox_daemon("sid", function, list(args), kwargs)
        return [json.loads(chunk.removeprefix("data:")) async for chunk in stream]


async def test_a_sync_function_streams_its_output_then_its_result() -> None:
    events = await _events(f"{_MODULE}:_speak", "hi", end="?")

    assert "".join(e["stdout"] for e in events[:-1] if "stdout" in e) == "hi?\n"
    assert "".join(e["stderr"] for e in events[:-1] if "stderr" in e) == "warn\n"
    assert from_b85(events[-1]["result"]) == "HI"


async def test_an_async_function_is_awaited() -> None:
    events = await _events(f"{_MODULE}:_aspeak", "ab")

    assert from_b85(events[-1]["result"]) == "abab"


async def test_every_event_is_one_sse_data_frame() -> None:
    with _stdio():
        frames = [chunk async for chunk in sandbox_daemon("sid", f"{_MODULE}:_speak", ["hi"], {})]

    assert all(frame.startswith("data:") and frame.endswith("\n\n") for frame in frames)


async def test_a_missing_module_is_reported_as_an_error_event() -> None:
    events = await _events("no_such_module_for_sandbox_daemon:f")

    assert events == [
        {"session_id": "sid", "error": "ValueError('Module no_such_module_for_sandbox_daemon not found')"}
    ]


async def test_a_missing_function_is_reported_as_an_error_event() -> None:
    events = await _events(f"{_MODULE}:no_such_function")

    assert events == [{"session_id": "sid", "error": f"ValueError('Function {_MODULE}.no_such_function() not found')"}]


async def test_an_exception_travels_in_both_forms() -> None:
    events = await _events(f"{_MODULE}:_fail")

    reply = events[-1]
    exception, _traceback = pickle.loads(base64.b85decode(reply["exception"]))
    descriptor, _ = pickle.loads(base64.b85decode(reply["exception_fallback"]))
    assert isinstance(exception, KeyError)
    assert descriptor[:3] == ("builtins", "KeyError", "'missing key'")


async def test_the_request_counter_returns_to_its_value() -> None:
    before = sse_server_daemon._active_requests

    await _events(f"{_MODULE}:_speak", "hi")
    await _events("no_such_module_for_sandbox_daemon:f")
    await _events(f"{_MODULE}:_fail")

    assert sse_server_daemon._active_requests == before


async def test_the_counter_counts_a_call_while_it_runs() -> None:
    before = sse_server_daemon._active_requests
    with _stdio():
        stream = sandbox_daemon("sid", f"{_MODULE}:_speak", ["hi"], {})
        await anext(stream)

        assert sse_server_daemon._active_requests == before + 1
        await stream.aclose()
    assert sse_server_daemon._active_requests == before


async def test_an_oversized_reply_is_refused_with_an_error_event() -> None:
    events = await _events(f"{_MODULE}:_huge")

    assert len(events) == 1
    assert "error" in events[0]


@pytest.mark.parametrize("learning", [True, False])
async def test_learning_mode_records_how_the_result_travelled(monkeypatch: pytest.MonkeyPatch, learning: bool) -> None:
    rules: list[Any] = []
    monkeypatch.setattr("pysandboxes.learning.is_learning_mode", lambda: learning)
    monkeypatch.setattr("pysandboxes.learning.add_learning_rule", rules.append)

    await _events(f"{_MODULE}:_speak", "hi")

    assert rules == (["remote-result-mode=data-only"] if learning else [])


async def test_a_cancelled_call_says_so() -> None:
    with _stdio():
        stream = sandbox_daemon("sid", f"{_MODULE}:_forever", [], {})
        task = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0.2)
        task.cancel()
        chunk = await task

    assert json.loads(chunk.removeprefix("data:")) == {"session_id": "sid", "cancelled": True}
