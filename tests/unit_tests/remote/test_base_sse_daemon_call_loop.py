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

    def __call__(self, *_: Any, **__: Any) -> "_Source":
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


def _run(monkeypatch: pytest.MonkeyPatch, source: _Source, retries: int) -> Any:
    _Source.attempts = 0
    monkeypatch.setattr(base_sse_daemon.sse_client, "EventSource", source)
    monkeypatch.setattr("pysandboxes._os_sandbox.get_token", lambda: "tok")
    daemon = SSEServerDaemon("tok", port=1234)
    daemon.max_connect_retry = retries
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
