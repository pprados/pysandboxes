import asyncio
import logging
import os
import threading
import weakref
from _weakref import ReferenceType
from typing import Any, Callable

from .bwrap_daemon import BWrapDaemon
from .firejail_daemon import FireJailDaemon
from . import ConfigLines
from .base_daemon import BaseDaemon
from .manage_loop import sandbox_loop, reset_sandbox_loop
from .subprocess_daemon import SubProcessDaemon
from .task_daemon import TaskDaemon
from .tools import is_in_sandbox

logger = logging.getLogger(__name__)

providers = {
    # TODO: faire un provider "transparent"
    "task": TaskDaemon(),  # Impossible to activate py-sandbox in this mode.
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

_current_daemon: ReferenceType[BaseDaemon] = None  # Current daemon used by the sandbox


@sandbox_loop
async def async_start_daemon(name: str,
                             log_level: int,
                             config: ConfigLines,
                             ) -> BaseDaemon:
    """
    Asynchronize version to start daemon by name.
    Returns daemon object when is starred
    """
    global _current_daemon
    if _current_daemon is not None and _current_daemon():
        logger.warning("Daemon already started")
        return _current_daemon()
    if name not in providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await providers[name].start(log_level, dict(os.environ), config, token=None)
    _current_daemon = weakref.ref(providers[name])
    assert providers[name].is_started == True
    return providers[name]


@sandbox_loop
async def async_shutdown_daemon():
    """
    Asynchronize version to shutdown the current daemon.
    Return when the daemon is shutdown.
    """
    global _current_daemon
    if not _current_daemon:
        logger.warning("Daemon not started when shutdown")
        return

    await _current_daemon().shutdown()
    assert _current_daemon().is_started == False
    _current_daemon = None


@sandbox_loop
def start_daemon(name: str,
                 log_level: int,
                 config: ConfigLines) -> BaseDaemon:
    """
    Synchronize version to start daemon by name.
    Returns daemon object when is starred
    """
    loop = asyncio.get_event_loop()
    start_event = threading.Event()

    async def _async_start_daemon():
        await async_start_daemon(name, log_level, config),
        start_event.set()

    loop.call_soon_threadsafe(
        lambda: loop.create_task(
            _async_start_daemon(),
            name="Start daemon")
    )
    start_event.wait()
    return _current_daemon()


@sandbox_loop
def shutdown_daemon() -> None:
    """
    Synchronize version to shutdown the current daemon.
    Return when the daemon is shutdown.
    """
    loop = asyncio.get_event_loop()
    stop_event = threading.Event()

    async def _async_shutdown_daemon():
        await loop.create_task(
            async_shutdown_daemon(),
            name="Shutdown daemon")
        stop_event.set()

    loop.call_soon_threadsafe(lambda: loop.create_task(_async_shutdown_daemon()))
    stop_event.wait()
    reset_sandbox_loop()  # FIXME: supprimer le sandbox loop, pour laisser la place


def get_token() -> str:
    global _current_daemon
    if _current_daemon is None or not _current_daemon():
        logger.warning("Daemon not started when trying to get token")
        return
    return _current_daemon().token


async def async_call_in_sandbox(
        func: Callable[..., Any],
        timeout: float,
        *args: Any,
        **kwargs: Any) -> Any:
    global _current_daemon
    if is_in_sandbox():
        return await func(*args, **kwargs)

    if _current_daemon is None or not _current_daemon():
        logger.warning("Daemon not started when trying to get token")
        return
    return await _current_daemon().async_call_in_sandbox(func, timeout, *args, **kwargs)


def call_in_sandbox(
        func: Callable[..., Any],
        timeout: float,
        *args: Any,
        **kwargs: Any) -> Any:
    global _current_daemon
    if is_in_sandbox():
        return func(*args, **kwargs)
    if _current_daemon is None or not _current_daemon():
        logger.warning("Daemon not started when trying to get token")
        return
    return _current_daemon().call_in_sandbox(func, timeout, *args, **kwargs)
