import asyncio
import logging
import os
import threading
import uuid
from typing import Any, Callable, Optional, Type, cast, Dict, Union

from .all_rules import AllRules
from .base_daemon import BaseDaemon
from .private_loop import sandbox_loop, reset_sandbox_loop, get_sandbox_loop
from .remote.none_daemon import NoneDaemon
from .remote.parameters import TIMEOUT_FOR_STOP_DAEMON
from .remote.sse_client_subprocess_daemon import SubProcessDaemon
from .remote.sse_firejail_daemon import FireJailSSEDaemon
from .remote.sse_server_daemon import SSEServerDaemon
from .remote.task_daemon import TaskDaemon
from .tools import is_in_sandbox, check_mixte_async_async, SyncOrAsyncFunc

logger = logging.getLogger(__name__)

providers_factory: dict[str, Type] = {
    # TODO: faire un provider "transparent"
    "_task": TaskDaemon,  # Impossible to activate py-sandbox in this mode.
    "_sse_server": SSEServerDaemon,  # Impossible to activate py-sandbox in this mode.
    "none": NoneDaemon,
    "subprocess": SubProcessDaemon,
    # "bwrap": BWrapDaemon(),
    "firejail": FireJailSSEDaemon,
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
    # TODO: external started daemon
    # TODO https://github.com/igo95862/bubblejail
    # TODO: paraméter apparmor https://mail.google.com/mail/u/0/#inbox/FMfcgzQbfxdJgGfjGcjPBxXNKmWqgPdK
}

DEFAULT_OS_SANDBOX = "subprocess"

# Singleton with the current daemon used by the sandbox
_current_daemon: Optional[BaseDaemon] = None  # TODO: use context?
_startup_counter = 0  # Number of time the daemon has been started

async def stop_incoming_call() -> None:
    # Stop to accept incoming call and wait the end of the current call
    _current_daemon._accept_incoming = False

def is_accept_incoming_call() -> bool:
    return (is_daemon_started()
            and _current_daemon._accept_incoming)

async def async_start_daemon(all_rules: AllRules,
                             *,
                             envs:Dict[str,str],
                             log_level: int,
                             init_fn: Optional[SyncOrAsyncFunc],
                             python_args: Optional[list[str]] = None,
                             ) -> BaseDaemon:
    """
    Asynchronize version to _start daemon by name.
    Returns daemon object when is starred
    """
    return await _async_start_daemon(all_rules,
                                     envs=envs,
                                     log_level=log_level,
                                     init_fn=init_fn,
                                     python_args=python_args)


_async_start_lock = asyncio.Lock()
_start_lock = threading.Lock()


async def _async_start_daemon(all_rules: AllRules,
                              envs:Dict[str,str],
                              log_level: int,
                              init_fn: Optional[SyncOrAsyncFunc],
                              python_args: Optional[list[str]] = None,
                              ) -> BaseDaemon:
    """
    Asynchronize version without the creation of the sandbox loop.
    It's used in run()
    """
    assert all_rules.os_sandbox
    async with _async_start_lock:
        global _current_daemon, _startup_counter
        if _current_daemon is not None:
            logger.info("Daemon already started")
            _startup_counter += 1
            return _current_daemon

        if all_rules.os_sandbox not in providers_factory:
            raise ValueError(f"Unknown daemon name: {all_rules.os_sandbox}")
        try:
            token = str(uuid.uuid4())
            os_provider:BaseDaemon = providers_factory[all_rules.os_sandbox](
                token,
                python_args=python_args
            )
            await os_provider._start(
                all_rules,
                envs=envs,
                log_level=log_level,
                init_fn=init_fn
            )
            _current_daemon = os_provider
            assert os_provider.is_started
            _startup_counter += 1
            return os_provider
        except Exception as e:
            _current_daemon = None
            raise e


async def async_stop_daemon(max_pending:int=0):
    """
    Asynchronize version to daemon_shutdown the current daemon.
    Return when the daemon is daemon_shutdown.
    """
    global _current_daemon, _startup_counter
    async with _async_start_lock:
        if not _current_daemon:
            logger.info("Daemon not started when stopping")
            return

        await _current_daemon._stop(max_pending)

async def async_shutdown_daemon(graceful_shutdown:bool = True):
    """
    Asynchronize version to daemon_shutdown the current daemon.
    Return when the daemon is daemon_shutdown.
    """
    global _current_daemon, _startup_counter
    async with _async_start_lock:
        if not _current_daemon:
            logger.info("Daemon not started when daemon_shutdown")
            _startup_counter -= 1
            if _startup_counter < 0:
                raise ValueError("Daemon daemon_shutdown more times than started")
            return

        if _startup_counter > 1:
            _startup_counter -= 1
            logger.info("Daemon not shutting down because the startup counter > 1")
            return
        await _current_daemon._shutdown(graceful_shutdown)
        assert not _current_daemon.is_started
        _current_daemon = None
        _startup_counter -= 1



def start_daemon(
        all_rules: AllRules,
        envs:Union[Dict[str,str],os._Environ],
        log_level: int,
        init_fn: Optional[SyncOrAsyncFunc] = None,
        python_args: Optional[list[str]] = None,
) -> BaseDaemon:
    """
    Synchronize version to _start daemon by name.
    Returns daemon object when is starred
    """
    assert all_rules.os_sandbox
    global _current_daemon, _startup_counter

    check_mixte_async_async()
    with _start_lock:
        if _current_daemon is not None:
            logger.info("Daemon already started")
            _startup_counter += 1
            return _current_daemon

        if all_rules.os_sandbox not in providers_factory:
            raise ValueError(f"Unknown daemon name: {all_rules.os_sandbox}")

        loop = get_sandbox_loop()
        start_event = threading.Event()

        async def _start_daemon_and_signal():

            await _async_start_daemon(all_rules,
                                      envs=envs,
                                      log_level=log_level,
                                      init_fn=init_fn,
                                      python_args=python_args,
                                      )
            start_event.set()
            logger.debug("Start event set")

        loop.call_soon_threadsafe(
            lambda: loop.create_task(
                _start_daemon_and_signal(),
                name="Start daemon")
        )
        if not start_event.wait():
            raise RuntimeError("Import to _start the sandbox")
        assert _current_daemon

        return cast(BaseDaemon, _current_daemon)


def is_daemon_started() -> bool:
    global _current_daemon
    return _current_daemon and _current_daemon.is_started

def _set_current_daemon(daemon:BaseDaemon) -> None:
    global _current_daemon
    _current_daemon = daemon

def shutdown_daemon(graceful_shutdown:bool = True) -> None:
    """
    Synchronize version to daemon_shutdown the current daemon.
    Return when the daemon is daemon_shutdown.
    """
    global _current_daemon, _startup_counter
    with _start_lock:
        if not _current_daemon:
            logger.info("Daemon not started when daemon_shutdown")
            _startup_counter -= 1
            if _startup_counter < 0:
                raise ValueError("Daemon daemon_shutdown more times than started")
            return
        loop = get_sandbox_loop()
        stop_event = threading.Event()

        @sandbox_loop
        async def _async_shutdown_daemon():
            await async_shutdown_daemon()
            stop_event.set()
            reset_sandbox_loop()

        loop.call_soon_threadsafe(
            lambda: loop.create_task(_async_shutdown_daemon(), name="daemon_shutdown daemon"))
        if not stop_event.wait(timeout=TIMEOUT_FOR_STOP_DAEMON):
            raise RuntimeError("Impossible to daemon_shutdown the sandbox")


def get_token() -> str:
    global _current_daemon
    assert _current_daemon is not None, "Daemon not started when trying to get token"
    return _current_daemon.token


async def async_call_in_sandbox(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any) -> Any:
    global _current_daemon
    if is_in_sandbox():
        return await func(*args, **kwargs)

    assert _current_daemon is not None, "Daemon not started"
    return await _current_daemon.async_call_in_sandbox(func,
                                                       False,
                                                       *args, **kwargs)


def call_in_sandbox(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any) -> Any:
    global _current_daemon
    if is_in_sandbox():
        return func(*args, **kwargs)
    assert _current_daemon is not None, ("Daemon not started. Use 'with sandboxes()' "
                                         "or 'pysandboxes.run()'")
    check_mixte_async_async()

    return _current_daemon.call_in_sandbox(func,
                                           False,
                                           *args, **kwargs)
