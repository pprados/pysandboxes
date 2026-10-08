# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The watchdog of a subprocess sandbox must never end the host application.

A sandbox child that kept dying made the parent watchdog call `os._exit(-2)`
after a few restarts, killing the trusted application that hosted it. A child
exiting with code 0 stopped the watchdog instead, leaving the daemon accepting
calls that nobody answered. Both must leave the daemon in a closed state where
every call raises at once.
"""

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
    retry = {"max_attempts": 2, "base_delay": 0.0, "max_delay": 0.0}
    return [
        (SubProcessDaemon("token", **retry), "_re_start"),
        (UnshareSSEDaemon("token", **retry), "_launch"),
    ]


@pytest.mark.parametrize("returncode", [3, 0])
@pytest.mark.parametrize("daemon, restart_name", _daemons(), ids=["subprocess", "unshare"])
async def test_a_child_that_keeps_dying_closes_the_daemon(daemon: Any, restart_name: str, returncode: int) -> None:
    restart = await _run_watchdog(daemon, restart_name, returncode)

    assert restart.await_count == 2
    assert not daemon._accept_incoming
    with pytest.raises(SandBoxProtocolError):
        await daemon.async_call_in_sandbox(print, False)
