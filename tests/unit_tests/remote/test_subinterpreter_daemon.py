# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests of the subinterpreter provider's host side: availability and reply framing."""

import os
import sys
import threading
import time

import pytest

from pysandboxes.e import SandBoxProtocolError
from pysandboxes.remote.subinterpreter_child import write_frame
from pysandboxes.remote.subinterpreter_daemon import SubInterpreterDaemon, _read_frame


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 12, 11)])
def test_unavailable_before_313(monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]) -> None:
    monkeypatch.setattr(sys, "version_info", version)
    reason = SubInterpreterDaemon.unavailable_reason()
    assert reason is not None and "3.13" in reason


@pytest.mark.skipif(sys.version_info < (3, 13), reason="the provider needs Python 3.13")
def test_available_from_313() -> None:
    assert SubInterpreterDaemon.unavailable_reason() is None


def test_a_frame_larger_than_the_pipe_buffer_goes_through() -> None:
    read_fd, write_fd = os.pipe()
    payload = os.urandom(300_000)
    writer = threading.Thread(target=write_frame, args=(write_fd, payload))
    writer.start()
    try:
        assert _read_frame(read_fd, time.monotonic() + 10) == payload
    finally:
        writer.join()
        os.close(read_fd)
        os.close(write_fd)


def test_a_silent_interpreter_times_out() -> None:
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(SandBoxProtocolError, match="in time"):
            _read_frame(read_fd, time.monotonic() + 0.1)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_a_closed_channel_is_reported() -> None:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    try:
        with pytest.raises(SandBoxProtocolError, match="closed"):
            _read_frame(read_fd, None)
    finally:
        os.close(read_fd)
