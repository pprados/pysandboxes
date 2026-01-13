import asyncio
import logging
import threading
import time
from asyncio import get_event_loop
from typing import Any, Optional

from pysandboxes.remote.bwrap_daemon import BWrapDaemon
from pysandboxes.remote.firejail_daemon import FireJailDaemon
from .base_daemon import BaseDaemon
from .manage_loop import get_sandbox_loop, sandbox_loop
from .subprocess_daemon import SubProcessDaemon
from .task_daemon import TaskDaemon

logger = logging.getLogger(__name__)

providers = {
    # TODO: faire un provider "transparent"
    "task": TaskDaemon(),  # For debug. Impossible to activate sandbox in this mode.
    "subprocess": SubProcessDaemon(),
    "bwrap": BWrapDaemon(),
    "firejail": FireJailDaemon(),
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
    # TODO: external started daemon
    # TODO https://github.com/igo95862/bubblejail
}

DEFAULT_OS_SANDBOX = "firejail"

_daemon_stated:Optional[BaseDaemon]=None
@sandbox_loop
async def async_start_daemon(name: str, log_level: int) -> BaseDaemon:
    global _daemon_stated
    if _daemon_stated:
        logger.warning("Daemon already started")
        return _daemon_stated
    if name not in providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await providers[name].start(log_level)
    _daemon_stated = providers[name]
    return providers[name]


@sandbox_loop
async def async_shutdown_daemon():
    global _daemon_stated
    if not _daemon_stated:
        logger.warning("Daemon not started")
        return

    await _daemon_stated.shutdown()
    _daemon_stated = None


# TODO: def shutdown_daemon(name:str)


@sandbox_loop
def start_daemon(name: str,
                 log_level: int) -> Any:
    loop = asyncio.get_event_loop()
    loop.call_soon_threadsafe(
        lambda: loop.create_task(
            async_start_daemon(name, log_level),
            name="ServerTask")
    )
    while not _daemon_stated:
        time.sleep(0.1)
    return _daemon_stated


@sandbox_loop
def shutdown_daemon() -> None:
    loop = asyncio.get_event_loop()
    start_event = threading.Event()

    async def _async_shutdown_daemon():
        await loop.create_task(
            async_shutdown_daemon(),
            name="ServerTask")
        start_event.set()
    loop.call_soon_threadsafe(lambda: loop.create_task(_async_shutdown_daemon()))
    start_event.wait()
    logger.debug("**** Daemon shutdown")