# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The watchdog of a subprocess sandbox must never end the host application.

A sandbox child that kept dying made the parent watchdog call `os._exit(-2)`
after a few restarts, killing the trusted application that hosted it. A child
exiting with code 0 stopped the watchdog instead, leaving the daemon accepting
calls that nobody answered. Both must leave the daemon in a closed state where
every call raises at once.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import SandBoxProtocolError
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon


class _HostExited(Exception):
    """Stands for `os._exit`, which must never be reached."""


class _DeadProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


class _PendingProcess:
    returncode = None

    async def wait(self) -> int:
        await asyncio.Event().wait()
        return 0

    def kill(self) -> None:
        pass


async def _run_watchdog(daemon: Any, restart_name: str, returncode: int) -> AsyncMock:
    daemon._process = _DeadProcess(returncode)
    daemon._accept_incoming = True
    daemon._is_started = True

    async def _restart(*args: Any, **kwargs: Any) -> None:
        daemon._process = _DeadProcess(returncode)
        daemon._accept_incoming = True

    restart = AsyncMock(side_effect=_restart)
    loop_name = "watchdog" if restart_name == "_re_start" else "_watchdog_loop"
    with (
        patch("os._exit", side_effect=_HostExited),
        patch.object(type(daemon), restart_name, restart),
    ):
        await getattr(daemon, loop_name)(None, envs={}, log_level=0, init_fn=None)
    return restart


def _daemons() -> list[tuple[Any, str]]:
    return [
        (SubProcessDaemon("token", max_attempts=2, base_delay=0.0, max_delay=0.0), "_re_start"),
        (UnshareSSEDaemon("token", max_attempts=2, base_delay=0.0, max_delay=0.0), "_launch"),
    ]


@pytest.mark.parametrize("returncode", [3, 0])
@pytest.mark.parametrize("daemon, restart_name", _daemons(), ids=["subprocess", "unshare"])
async def test_a_child_that_keeps_dying_closes_the_daemon(daemon: Any, restart_name: str, returncode: int) -> None:
    restart = await _run_watchdog(daemon, restart_name, returncode)

    assert restart.await_count == 2
    assert not daemon._accept_incoming
    with pytest.raises(SandBoxProtocolError):
        await daemon.async_call_in_sandbox(print, False)


@pytest.mark.parametrize(
    "daemon,watchdog_method",
    [
        pytest.param(SubProcessDaemon("token"), "watchdog", id="subprocess"),
        pytest.param(UnshareSSEDaemon("token"), "_watchdog_loop", id="unshare"),
    ],
)
async def test_shutdown_waits_for_the_watchdog_to_finish(daemon: Any, watchdog_method: str) -> None:
    daemon._process = _PendingProcess()
    daemon._is_started = False
    watchdog = asyncio.create_task(
        getattr(daemon, watchdog_method)(None, envs={}, log_level=0, init_fn=None),
        name="ControlDaemon",
    )
    daemon._watchdog = watchdog
    await asyncio.sleep(0)

    try:
        await daemon._shutdown(graceful_shutdown=False)

        assert watchdog.done()
    finally:
        if not watchdog.done():
            watchdog.cancel()
            await watchdog
