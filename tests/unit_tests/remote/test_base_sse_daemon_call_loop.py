# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Retry loop and event handling of `BaseSSESandbox.async_call_in_sandbox`, against a fake event source."""

import asyncio
import json
from typing import Any

import pytest

from pysandboxes.e import SandBoxProtocolError
from pysandboxes.remote import base_sse_daemon
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon
from pysandboxes.remote.tools import to_b85


class _Event:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = json.dumps(data)


class _Source:
    """Stands for `EventSource`: refuses the first `refusals` connections, then streams `events`."""

    attempts = 0

    def __init__(self, events: list[dict[str, Any]], refusals: int = 0, limit: int = 20) -> None:
        self.events = events
        self.refusals = refusals
        self.limit = limit

    def __call__(self, *_: Any, **kwargs: Any) -> "_Source":
        self.kwargs = kwargs
        type(self).attempts += 1
        assert type(self).attempts <= self.limit, "the retry loop does not stop"
        return self

    async def __aenter__(self) -> "_Source":
        if type(self).attempts <= self.refusals:
            raise ConnectionRefusedError("refused")
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    def __aiter__(self) -> "_Source":
        self._iter = iter(self.events)
        return self

    async def __anext__(self) -> _Event:
        try:
            return _Event(next(self._iter))
        except StopIteration:
            raise StopAsyncIteration from None


def _run(monkeypatch: pytest.MonkeyPatch, source: _Source, retries: int, host: str | None = None) -> Any:
    _Source.attempts = 0
    monkeypatch.setattr(base_sse_daemon.sse_client, "EventSource", source)
    monkeypatch.setattr("pysandboxes._os_sandbox.get_token", lambda: "tok")
    daemon = SSEServerDaemon("tok", port=1234)
    daemon.max_connect_retry = retries
    if host is not None:
        daemon.host = host
    daemon._accept_incoming = True

    async def func() -> None:
        raise AssertionError("must not run")

    return asyncio.run(daemon.async_call_in_sandbox(func, False))


def test_a_result_event_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, _Source([{"result": to_b85(41)}]), 3) == 41


def test_a_refused_connection_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _Source([{"result": to_b85("ok")}], refusals=2)

    assert _run(monkeypatch, source, 3) == "ok"
    assert _Source.attempts == 3


def test_every_attempt_is_used_before_giving_up(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SandBoxProtocolError, match="No result received"):
        _run(monkeypatch, _Source([], refusals=99), 3)

    assert _Source.attempts == 3


@pytest.mark.parametrize("retries", [0, -1])
def test_no_attempt_is_made_without_a_retry_budget(monkeypatch: pytest.MonkeyPatch, retries: int) -> None:
    with pytest.raises(SandBoxProtocolError, match="No result received"):
        _run(monkeypatch, _Source([{"result": to_b85(1)}], limit=5), retries)

    assert _Source.attempts == 0


def test_a_stream_without_outcome_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SandBoxProtocolError, match="No result received"):
        _run(monkeypatch, _Source([{"stdout": "x"}]), 3)

    assert _Source.attempts == 1


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"error": "bad"}, "Sandbox reported: bad"),
        ({"cancelled": True}, "cancelled"),
    ],
)
def test_error_events_raise_a_protocol_error(
    monkeypatch: pytest.MonkeyPatch, event: dict[str, Any], message: str
) -> None:
    with pytest.raises(SandBoxProtocolError, match=message):
        _run(monkeypatch, _Source([event, {"result": to_b85(1)}]), 3)


def test_output_events_are_forwarded(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    events = [{"stdout": "out"}, {"stderr": "err"}, {"result": to_b85(None)}]

    _run(monkeypatch, _Source(events), 3)

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("out", "err")


class _Session:
    """Stands for `aiohttp.ClientSession`: remembers whether it was closed."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_loopback_call_uses_one_ipv4_session_and_closes_it(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    sessions: list[_Session] = []

    def make_session(**kwargs: Any) -> _Session:
        sessions.append(_Session(**kwargs))
        return sessions[-1]

    monkeypatch.setattr(base_sse_daemon.aiohttp, "ClientSession", make_session)
    source = _Source([{"result": to_b85(1)}])

    _run(monkeypatch, source, 3, host=host)

    assert [s.closed for s in sessions] == [True]
    assert source.kwargs["session"] is sessions[0]


def test_a_remote_call_leaves_the_session_to_the_event_source(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _Source([{"result": to_b85(1)}])

    assert _run(monkeypatch, source, 3, host="sandbox.example") == 1

    assert "session" not in source.kwargs


@pytest.mark.parametrize(
    ("value", "valid"),
    [(0, True), (1, True), (2**31 - 1, True), (-1, False), (2**31, False), (True, False), (1.0, False), ("1", False)],
)
def test_a_line_number_is_an_int_within_the_c_int_range(value: Any, valid: bool) -> None:
    assert base_sse_daemon._is_lineno(value) is valid
