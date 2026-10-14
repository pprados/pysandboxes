# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Restoring the original stream when a `WrapperIO` goes away."""

import contextvars
import io

from pysandboxes.remote.catch_stdio import WrapperIO


def test_deleting_a_redirected_wrapper_restores_the_original_stream() -> None:
    original = io.StringIO()
    stream: contextvars.ContextVar[io.TextIOBase] = contextvars.ContextVar("stream", default=original)
    wrapper = WrapperIO(stream)
    wrapper.set_context(io.StringIO())

    wrapper.__del__()

    assert stream.get() is original


def test_deleting_a_wrapper_that_redirected_nothing_leaves_the_stream_alone() -> None:
    current = io.StringIO()
    stream: contextvars.ContextVar[io.TextIOBase] = contextvars.ContextVar("stream", default=current)

    WrapperIO(stream).__del__()

    assert stream.get() is current
