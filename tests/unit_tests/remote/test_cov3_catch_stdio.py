# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``catch_stdio``: flushes, attribute delegation of ``WrapperIO``, and a queue that is neither queue type."""

import asyncio
import contextvars
import io
import sys
from typing import Any
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import private_loop
from pysandboxes.remote import catch_stdio
from pysandboxes.remote.catch_stdio import QueueStringIO, WrapperIO, acatch_stdio


class _Stream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0
        self.label = "original"

    def flush(self) -> None:
        self.flushes += 1


def test_queue_string_io_flush_flushes_its_buffer() -> None:
    stream = QueueStringIO(type="stdout", queue=None)
    buffer = _Stream()
    stream._buffer = buffer

    stream.flush()

    assert buffer.flushes == 1


def test_wrapper_flush_flushes_the_stream_of_the_current_context() -> None:
    default, current = _Stream(), _Stream()
    wrapper = WrapperIO(contextvars.ContextVar("t_flush", default=default))
    wrapper.set_context(current)

    wrapper.flush()

    assert (current.flushes, default.flushes) == (1, 0)


def test_unknown_attributes_are_read_and_written_on_the_original_stream() -> None:
    default = _Stream()
    wrapper = WrapperIO(contextvars.ContextVar("t_attr", default=default))
    wrapper.set_context(_Stream())

    assert wrapper.label == "original"
    wrapper.label = "changed"

    assert default.label == "changed"
    assert "label" not in vars(wrapper)


def test_an_own_attribute_not_yet_set_raises_attribute_error() -> None:
    wrapper = WrapperIO.__new__(WrapperIO)

    with pytest.raises(AttributeError):
        _ = wrapper._old

    # Complete the object, so its ``__del__`` does not fail during garbage collection.
    original = io.StringIO()
    wrapper._context = contextvars.ContextVar("t_unset", default=original)
    wrapper._old = None


class _PutOnly:
    """A queue with ``put`` that is neither a ``queue.Queue`` nor an ``asyncio.Queue``."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    def put(self, item: Any) -> None:
        self.items.append(item)


def _hello() -> str:
    print("hello")
    return "done"


def _fail() -> None:
    print("before")
    raise KeyError("missing")


@pytest.fixture
async def stdio(monkeypatch: pytest.MonkeyPatch) -> tuple[WrapperIO, WrapperIO]:
    monkeypatch.setattr(private_loop, "_background_loop_ref", asyncio.get_running_loop())
    host_out, host_err = io.StringIO(), io.StringIO()
    return (
        catch_stdio.WrapperIO(contextvars.ContextVar("t3_stdout", default=host_out)),
        catch_stdio.WrapperIO(contextvars.ContextVar("t3_stderr", default=host_err)),
    )


async def _call(stdio: tuple[WrapperIO, WrapperIO], q: Any, fn: Any) -> dict[str, Any]:
    with patch.object(sys, "stdout", stdio[0]), patch.object(sys, "stderr", stdio[1]):
        return await asyncio.create_task(acatch_stdio(q, fn, {}))


async def test_an_other_queue_type_still_returns_the_result(stdio: tuple[WrapperIO, WrapperIO]) -> None:
    q = _PutOnly()

    result = await _call(stdio, q, _hello)

    assert result == {"result": "done", "stdout": "hello\n", "stderr": ""}
    assert q.items[0] == {"stdout": "hello"}


async def test_an_other_queue_type_still_returns_the_exception(stdio: tuple[WrapperIO, WrapperIO]) -> None:
    q = _PutOnly()

    result = await _call(stdio, q, _fail)

    exc, _tb = result["exception"]
    assert type(exc) is KeyError and exc.args == ("missing",)
    assert result["stdout"] == "before\n"
    assert q.items[0] == {"stdout": "before"}
