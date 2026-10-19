# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Exception transport and call gate of `BaseSSESandbox` that the other tests leave unobserved."""

import asyncio
from types import TracebackType
from typing import Any

import pytest
import tblib

from pysandboxes.e import RestrictedUnpicklingError, SandBoxProtocolError
from pysandboxes.remote import base_sse_daemon
from pysandboxes.remote.base_sse_daemon import _attach_remote_traceback, _rebuild_remote_exception
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon
from pysandboxes.remote.tools import to_b85


def _raise_through(depth: int) -> BaseException:
    def level(remaining: int) -> None:
        if remaining:
            level(remaining - 1)
        else:
            raise ValueError("boom")

    try:
        level(depth)
    except ValueError as exc:
        return exc
    raise AssertionError("unreachable")


def _chain(tb: TracebackType | None) -> int:
    length = 0
    while tb is not None:
        length += 1
        tb = tb.tb_next
    return length


class TestAttachRemoteTraceback:
    def test_the_three_transport_frames_are_dropped(self) -> None:
        exc = _raise_through(6)
        frames = _chain(exc.__traceback__)

        attached = _attach_remote_traceback(ValueError("denied"), tblib.Traceback(exc.__traceback__))

        assert _chain(attached.__traceback__) == frames - 3

    def test_a_short_traceback_keeps_its_last_frame(self) -> None:
        exc = _raise_through(0)
        exc.__traceback__ = exc.__traceback__.tb_next if exc.__traceback__ else None  # type: ignore[union-attr]

        attached = _attach_remote_traceback(ValueError("denied"), tblib.Traceback(exc.__traceback__))

        assert _chain(attached.__traceback__) == 1

    def test_an_empty_traceback_still_returns_the_exception(self) -> None:
        exception = ValueError("denied")

        class Empty(tblib.Traceback):
            def as_traceback(self) -> None:  # type: ignore[override]
                return None

        empty = Empty(_raise_through(0).__traceback__)

        assert _attach_remote_traceback(exception, empty) is exception
        assert exception.__traceback__ is None

    def test_a_foreign_traceback_is_refused(self) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _attach_remote_traceback(ValueError("x"), "not a traceback")

    def test_a_cyclic_chain_is_refused_instead_of_looping(self) -> None:
        serial = tblib.Traceback(_raise_through(3).__traceback__)
        serial.tb_next.tb_next = serial  # type: ignore[union-attr]

        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _attach_remote_traceback(ValueError("x"), serial)

    def test_a_chain_longer_than_any_real_one_is_refused(self) -> None:
        serial = tblib.Traceback(_raise_through(0).__traceback__)
        node = serial
        for _ in range(base_sse_daemon._MAX_TRACEBACK_FRAMES + 1):
            node.tb_next = tblib.Traceback(_raise_through(0).__traceback__)
            node = node.tb_next

        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _attach_remote_traceback(ValueError("x"), serial)

    @pytest.mark.parametrize("lineno", [-1, 2**31, 2**70, 1.5, "7", True, None])
    def test_a_line_number_out_of_range_or_of_another_type_is_refused(self, lineno: Any) -> None:
        serial = tblib.Traceback(_raise_through(1).__traceback__)
        serial.tb_lineno = lineno

        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _attach_remote_traceback(ValueError("x"), serial)

    @pytest.mark.parametrize(
        "damage",
        [
            lambda tb: setattr(tb.tb_frame, "f_locals", {"__traceback_maker": ValueError}),
            lambda tb: setattr(tb.tb_frame, "f_globals", {"__traceback_maker": "x"}),
            lambda tb: setattr(tb.tb_frame.f_code, "co_name", 7),
            lambda tb: setattr(tb.tb_frame.f_code, "co_filename", b"x"),
            lambda tb: setattr(tb, "tb_frame", object()),
            lambda tb: delattr(tb, "tb_frame"),
        ],
    )
    def test_a_frame_holding_more_than_tblib_builds_is_refused(self, damage: Any) -> None:
        serial = tblib.Traceback(_raise_through(1).__traceback__)
        damage(serial)

        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _attach_remote_traceback(ValueError("x"), serial)


def _tb_payload(exc: BaseException) -> Any:
    return tblib.Traceback(exc.__traceback__)


class TestRebuildRemoteException:
    def test_the_rich_form_is_used_when_there_is_one(self) -> None:
        exc = _raise_through(5)
        payload = to_b85((ValueError("rich"), _tb_payload(exc)))
        fallback = to_b85((("builtins", "KeyError", "descriptor", []), _tb_payload(exc)))

        rebuilt = _rebuild_remote_exception(payload, fallback)

        assert isinstance(rebuilt, ValueError)
        assert str(rebuilt) == "rich"

    def test_without_a_rich_form_the_descriptor_is_used(self) -> None:
        exc = _raise_through(5)
        fallback = to_b85((("builtins", "KeyError", "descriptor", ["d1"]), _tb_payload(exc)))

        rebuilt = _rebuild_remote_exception("", fallback)

        assert isinstance(rebuilt, KeyError)

    def test_neither_form_is_refused(self) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="neither an exception nor a descriptor"):
            _rebuild_remote_exception("", None)

    @pytest.mark.parametrize(
        "descriptor",
        [
            ("builtins", "KeyError", "message"),
            ("builtins", "KeyError", "message", [], "extra"),
            ("builtins", "KeyError", "message", "not a list"),
            ("builtins", "KeyError", "message", [1]),
            (1, "KeyError", "message", []),
        ],
    )
    def test_a_descriptor_of_another_shape_is_refused(self, descriptor: tuple[Any, ...]) -> None:
        payload = to_b85((descriptor, _tb_payload(_raise_through(5))))

        with pytest.raises(RestrictedUnpicklingError, match="unexpected shape"):
            _rebuild_remote_exception("", payload)


class TestCallGate:
    def test_the_result_channel_is_guarded_and_data_only_by_default(self) -> None:
        daemon = SSEServerDaemon("tok", port=1234)

        assert daemon._result_guard is True
        assert daemon._result_data_only is True

    async def _call(self, daemon: SSEServerDaemon) -> None:
        async def func() -> None:
            raise AssertionError("must not run")

        await daemon.async_call_in_sandbox(func, False)

    def test_a_dead_sandbox_raises_its_failure_on_every_call(self) -> None:
        daemon = SSEServerDaemon("tok", port=1234)
        daemon._failure = "the sandbox died"

        with pytest.raises(SandBoxProtocolError, match="the sandbox died"):
            asyncio.run(self._call(daemon))

    def test_a_live_sandbox_that_stopped_accepting_refuses_with_its_own_message(self) -> None:
        daemon = SSEServerDaemon("tok", port=1234)

        with pytest.raises(SandBoxProtocolError, match="being stopped"):
            asyncio.run(self._call(daemon))
