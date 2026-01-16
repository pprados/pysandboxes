import asyncio
import logging
import os
import threading
import weakref
from _weakref import ReferenceType
from typing import Any, Callable

from .firejail_daemon import FireJailDaemon
from .subprocess_daemon import SubProcessDaemon
from .task_daemon import TaskDaemon
from .tools import is_in_sandbox, check_mixte_async_async
from ..base_daemon import BaseDaemon
from ..manage_loop import sandbox_loop, reset_sandbox_loop, get_sandbox_loop
from ..types import ConfigLines

logger = logging.getLogger(__name__)

providers = {
    # TODO: faire un provider "transparent"
    "task": TaskDaemon(),  # Impossible to activate py-sandbox in this mode.
    "subprocess": SubProcessDaemon(),
    # "bwrap": BWrapDaemon(),
    "firejail": FireJailDaemon(),
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
    # TODO: external started daemon
    # TODO https://github.com/igo95862/bubblejail
    # TODO: paraméter apparmor https://mail.google.com/mail/u/0/#inbox/FMfcgzQbfxdJgGfjGcjPBxXNKmWqgPdK
}

DEFAULT_OS_SANDBOX = "subprocess"

_current_daemon: ReferenceType[BaseDaemon] = None  # Current daemon used by the sandbox
_startup_counter = 0  # Number of time the daemon has been started


@sandbox_loop
async def async_start_daemon(name: str,
                             log_level: int,
                             config: ConfigLines,
                             ) -> BaseDaemon:
    """
    Asynchronize version to start daemon by name.
    Returns daemon object when is starred
    """
    return await _async_start_daemon(name, log_level, config)


_async_start_lock = asyncio.Lock()
_async_stop_lock = asyncio.Lock()
_start_lock = threading.Lock()
_stop_lock = threading.Lock()


async def _async_start_daemon(name: str,
                              log_level: int,
                              config: ConfigLines,
                              ) -> BaseDaemon:
    """
    Asynchronize version without the creation of the sandbox loop.
    It's used in run()
    """
    global _current_daemon, _startup_counter
    async with _async_start_lock:
        if _current_daemon is not None and _current_daemon():
            logger.info("Daemon already started")
            _startup_counter += 1
            return _current_daemon()

        if name not in providers:
            raise ValueError(f"Unknown daemon name: {name}")
        try:
            await providers[name].start(log_level, dict(os.environ), config, token=None)
            _current_daemon = weakref.ref(providers[name])
            assert providers[name].is_started == True
            _startup_counter += 1
            return providers[name]
        except Exception as e:
            _current_daemon = None
            raise e


# @sandbox_loop
async def async_shutdown_daemon():
    """
    Asynchronize version to shutdown the current daemon.
    Return when the daemon is shutdown.
    """
    global _current_daemon, _startup_counter
    async with _async_start_lock,_async_stop_lock:
        if not _current_daemon:
            logger.info("Daemon not started when shutdown")
            _startup_counter -= 1
            if _startup_counter < 0:
                raise ValueError("Daemon shutdown more times than started")
            return

        if _startup_counter > 1:
            _startup_counter -= 1
            logger.info("Daemon not shutting down because the startup counter > 1")
            return
        await _current_daemon().shutdown()
        assert _current_daemon().is_started == False  # FIXME: peut etre faul, si plusieur entrée
        _current_daemon = None
        _startup_counter -= 1


def start_daemon(name: str,
                 log_level: int,
                 config: ConfigLines,
                 *,
                 timeout: int = 60) -> BaseDaemon:
    """
    Synchronize version to start daemon by name.
    Returns daemon object when is starred
    """
    global _current_daemon, _startup_counter
    with _start_lock:
        if _current_daemon is not None and _current_daemon():
            logger.info("Daemon already started")
            _startup_counter += 1
            return _current_daemon()

        if name not in providers:
            raise ValueError(f"Unknown daemon name: {name}")

        # loop = asyncio.get_event_loop()
        loop = get_sandbox_loop()
        start_event = threading.Event()

        async def _start_daemon_and_signal():
            await _async_start_daemon(name, log_level, config)
            start_event.set()
            logger.debug("Start event set")

        loop.call_soon_threadsafe(
            lambda: loop.create_task(
                _start_daemon_and_signal(),
                name="Start daemon")
        )
        if not start_event.wait(timeout=timeout):
            raise RuntimeError("Import to start the sandbox")
        assert _current_daemon

        return _current_daemon()


def is_daemon_started() -> bool:
    global _current_daemon
    return False if _current_daemon is None else _current_daemon().is_started


@sandbox_loop
def shutdown_daemon() -> None:
    """
    Synchronize version to shutdown the current daemon.
    Return when the daemon is shutdown.
    """
    global _current_daemon, _startup_counter
    with _start_lock,_stop_lock:
        if not _current_daemon:
            logger.info("Daemon not started when shutdown")
            _startup_counter -= 1
            if _startup_counter < 0:
                raise ValueError("Daemon shutdown more times than started")
            return
        loop = get_sandbox_loop()
        stop_event = threading.Event()

        async def _async_shutdown_daemon():
            await async_shutdown_daemon()
            stop_event.set()

        loop.call_soon_threadsafe(
            lambda: loop.create_task(_async_shutdown_daemon(), name="shutdown daemon"))
        if not stop_event.wait(timeout=10):
            raise RuntimeError("Import to shutdown the sandbox")
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
        raise RuntimeError("Daemon not started when trying to get token")
    check_mixte_async_async()

    return _current_daemon().call_in_sandbox(func, timeout, *args, **kwargs)
