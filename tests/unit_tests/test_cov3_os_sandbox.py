# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``_os_sandbox``: shutdowns without a daemon, failing or stuck shutdowns, calls made from inside the sandbox."""

import asyncio
import threading
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox
from pysandboxes.base_daemon import FakeDaemon


class _Boom(RuntimeError):
    pass


class _Daemon(FakeDaemon):
    """A started provider whose shutdown can fail or wait on a gate."""

    def __init__(self, shutdown_error: Exception | None = None, gate: asyncio.Event | None = None) -> None:
        super().__init__("token")
        self._is_started = True
        self.shutdown_error = shutdown_error
        self.gate = gate
        self.shutdowns: list[bool] = []

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.shutdown_error is not None:
            raise self.shutdown_error
        self.shutdowns.append(graceful_shutdown)
        self._is_started = False


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(_os_sandbox, "_async_start_lock", asyncio.Lock())
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0
    yield
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0


def test_set_current_daemon_installs_the_daemon_seen_by_the_module() -> None:
    daemon = _Daemon()

    _os_sandbox._set_current_daemon(daemon)

    assert _os_sandbox._current_daemon is daemon
    assert _os_sandbox.is_daemon_started()
    assert _os_sandbox.get_token() == "token"


async def test_an_async_shutdown_without_a_daemon_still_consumes_a_pending_start() -> None:
    _os_sandbox._startup_counter = 1

    await _os_sandbox.async_shutdown_daemon()

    assert _os_sandbox._startup_counter == 0
    with pytest.raises(ValueError, match="more times than started"):
        await _os_sandbox.async_shutdown_daemon()


def test_a_sync_shutdown_without_a_daemon_still_consumes_a_pending_start() -> None:
    _os_sandbox._startup_counter = 1

    _os_sandbox.shutdown_daemon()

    assert _os_sandbox._startup_counter == 0
    with pytest.raises(ValueError, match="more times than started"):
        _os_sandbox.shutdown_daemon()


def test_a_failing_sync_shutdown_reraises_the_provider_error() -> None:
    daemon = _Daemon(shutdown_error=_Boom("vm refused to stop"))
    _os_sandbox._set_current_daemon(daemon)
    _os_sandbox._startup_counter = 1

    with pytest.raises(_Boom, match="vm refused to stop"):
        _os_sandbox.shutdown_daemon()

    assert _os_sandbox._current_daemon is daemon
    assert _os_sandbox._startup_counter == 1


def test_a_stuck_sync_shutdown_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_os_sandbox, "TIMEOUT_FOR_STOP_DAEMON", 0.2)
    loop = _os_sandbox.get_sandbox_loop()
    gate = asyncio.Event()
    daemon = _Daemon(gate=gate)
    _os_sandbox._set_current_daemon(daemon)
    _os_sandbox._startup_counter = 1
    try:
        with pytest.raises(RuntimeError, match="Impossible to shutdown the sandbox"):
            _os_sandbox.shutdown_daemon()
        assert daemon.shutdowns == []
    finally:
        # Let the pending shutdown end, so it never runs into a later test.
        done = threading.Event()

        async def _release_and_wait() -> None:
            gate.set()
            while _os_sandbox._current_daemon is not None:
                await asyncio.sleep(0.01)
            done.set()

        loop.call_soon_threadsafe(lambda: loop.create_task(_release_and_wait()))
        assert done.wait(5)
    assert daemon.shutdowns == [True]


async def test_an_async_call_from_inside_the_sandbox_runs_the_function_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_os_sandbox, "is_in_sandbox", lambda: True)

    async def add(a: int, *, b: int) -> int:
        return a + b

    assert await _os_sandbox.async_call_in_sandbox(add, 2, b=3) == 5


def test_a_call_from_inside_the_sandbox_runs_the_function_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_os_sandbox, "is_in_sandbox", lambda: True)

    assert _os_sandbox.call_in_sandbox(divmod, 7, 2) == (3, 1)


def test_a_call_from_outside_reaches_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    class _Calling(_Daemon):
        def call_in_sandbox(self, func, _force_incomming, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((func, _force_incomming, args, kwargs))
            return "remote"

    _os_sandbox._set_current_daemon(_Calling())

    assert _os_sandbox.call_in_sandbox(divmod, 7, b=2) == "remote"
    assert calls == [(divmod, False, (7,), {"b": 2})]
