# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""
This module manages the lifecycle of different sandbox daemons.

It provides functions to start, stop, and interact with various sandboxing
providers like subprocess, firejail, etc. It maintains a singleton instance
of the currently active daemon.
"""

import asyncio
import logging
import threading
import uuid
from typing import Any, Callable, Type, cast

from .all_rules import AllRules
from .base_daemon import BaseDaemon
from .private_loop import (
    _reset_sandbox_loop,
    get_sandbox_loop,
    sandbox_loop,
)
from .remote.none_daemon import NoneDaemon
from .remote.parameters import TIMEOUT_FOR_STOP_DAEMON
from .remote.sse_client_subprocess_daemon import SubProcessDaemon
from .remote.sse_firejail_daemon import FireJailSSEDaemon
from .remote.sse_server_daemon import SSEServerDaemon
from .remote.sse_unshare_daemon import UnshareSSEDaemon
from .remote.task_daemon import TaskDaemon
from .tools import Environ, SyncOrAsyncFunc, check_mixte_async_async, is_in_sandbox

logger = logging.getLogger(__name__)

# A factory to create daemon instances from their names.
providers_factory: dict[str, Type] = {
    "_task": TaskDaemon,  # Impossible to activate py-sandbox in this mode.
    "_sse_server": SSEServerDaemon,  # Impossible to activate py-sandbox in this mode.
    "none": NoneDaemon,
    "subprocess": SubProcessDaemon,
    # "bwrap": BWrapDaemon(),
    "firejail": FireJailSSEDaemon,
    "unshare": UnshareSSEDaemon,
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
    # TODO: external started daemon
    # TODO https://github.com/igo95862/bubblejail
    # TODO: paraméter apparmor https://mail.google.com/mail/u/0/#inbox/FMfcgzQbfxdJgGfjGcjPBxXNKmWqgPdK
}

DEFAULT_OS_SANDBOX = "subprocess"

# Singleton with the current daemon used by the sandbox
_current_daemon: BaseDaemon | None = None
# Number of times the daemon has been started. Used for reference counting.
_startup_counter = 0


async def stop_incoming_call() -> None:
    """
    Stops the current daemon from accepting new incoming calls.

    This function sets a flag on the daemon to prevent it from processing
    new requests, allowing for a graceful shutdown.
    """
    # Stop to accept incoming call and wait the end of the current call
    global _current_daemon
    if _current_daemon:
        _current_daemon._accept_incoming = False


def is_accept_incoming_call() -> bool:
    """
    Checks if the current daemon is started and accepting incoming calls.

    Returns:
        True if the daemon is running and accepting calls, False otherwise.
    """
    return (
        is_daemon_started()
        and _current_daemon is not None
        and _current_daemon._accept_incoming
    )


async def async_start_daemon(
    all_rules: AllRules,
    *,
    envs: Environ,
    log_level: int,
    init_fn: SyncOrAsyncFunc | None,
    python_args: list[str] | None = None,
) -> BaseDaemon:
    """
    Core logic to asynchronously start a daemon.

    It ensures that only one daemon is started at a time using a lock.
    If a daemon is already running, it increments a counter and returns
    the existing instance.

    Args:
        all_rules: The security rules for the sandbox.
        envs: Environment variables for the sandbox process.
        log_level: The logging level for the daemon.
        init_fn: An optional initialization function to run in the sandbox.
        python_args: Optional arguments for the Python interpreter in the sandbox.

    Returns:
        The started daemon instance.

    Raises:
        ValueError: If the specified os_sandbox name is unknown.
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
            os_provider: BaseDaemon = providers_factory[all_rules.os_sandbox](
                token, python_args=python_args
            )
            await os_provider._start(
                all_rules, envs=envs, log_level=log_level, init_fn=init_fn
            )
            _current_daemon = os_provider
            assert os_provider.is_started
            _startup_counter += 1
            return os_provider
        except Exception as e:
            _current_daemon = None
            raise e


_async_start_lock = asyncio.Lock()
_start_lock = threading.Lock()


async def async_stop_daemon(max_pending: int = 0) -> None:
    """
    Asynchronously stops the current daemon.

    Args:
        max_pending: The maximum number of pending tasks to wait for.
    """
    global _current_daemon, _startup_counter
    async with _async_start_lock:
        if not _current_daemon:
            logger.info("Daemon not started when stopping")
            return

        await _current_daemon._stop(max_pending)


async def async_shutdown_daemon(graceful_shutdown: bool = True) -> None:
    """
    Asynchronously shuts down the current daemon.

    This function decrements the startup counter. If the counter reaches zero,
    it proceeds to shut down the daemon.

    Args:
        graceful_shutdown: If True, waits for pending tasks to complete.
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
        # Try a graceful shutdown
        await _current_daemon._shutdown(graceful_shutdown)
        assert not _current_daemon.is_started
        _current_daemon = None
        _startup_counter -= 1


def start_daemon(
    all_rules: AllRules,
    *,
    envs: Environ,
    log_level: int,
    init_fn: SyncOrAsyncFunc | None = None,
    python_args: list[str] | None = None,
) -> BaseDaemon:
    """
    Synchronously starts a daemon by name.

    This function is a synchronous wrapper around the async start logic.
    It is thread-safe.

    Args:
        all_rules: The security rules for the sandbox.
        envs: Environment variables for the sandbox process.
        log_level: The logging level for the daemon.
        init_fn: An optional initialization function to run in the sandbox.
        python_args: Optional arguments for the Python interpreter in the sandbox.

    Returns:
        The started daemon instance.

    Raises:
        RuntimeError: If the daemon fails to start.
        ValueError: If the specified os_sandbox name is unknown.
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

        async def _start_daemon_and_signal() -> None:
            """Helper to run async start and signal completion."""
            await async_start_daemon(
                all_rules,
                envs=envs,
                log_level=log_level,
                init_fn=init_fn,
                python_args=python_args,
            )
            start_event.set()
            logger.debug("Start event set")

        loop.call_soon_threadsafe(
            lambda: loop.create_task(_start_daemon_and_signal(), name="Start daemon")
        )
        if not start_event.wait():
            raise RuntimeError("Import to _start the sandbox")
        assert _current_daemon

    return cast(BaseDaemon, _current_daemon)


def is_daemon_started() -> bool:
    """
    Checks if the daemon is currently started.

    Returns:
        True if the daemon is started, False otherwise.
    """
    global _current_daemon
    return _current_daemon is not None and _current_daemon.is_started


def _set_current_daemon(daemon: BaseDaemon) -> None:
    """
    Sets the global current daemon instance.

    Args:
        daemon: The daemon instance to set as current.
    """
    global _current_daemon
    _current_daemon = daemon


def shutdown_daemon(graceful_shutdown: bool = True) -> None:
    """
    Synchronously shuts down the current daemon.

    This is a thread-safe, synchronous wrapper around the async shutdown logic.

    Args:
        graceful_shutdown: If True, waits for pending tasks to complete.

    Raises:
        RuntimeError: If the daemon fails to shut down within the timeout.
        ValueError: If shutdown is called more times than start.
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
        async def _async_shutdown_daemon() -> None:
            """Helper to run async shutdown and signal completion."""
            await async_shutdown_daemon()
            stop_event.set()
            _reset_sandbox_loop()

        loop.call_soon_threadsafe(
            lambda: loop.create_task(
                _async_shutdown_daemon(), name="daemon_shutdown daemon"
            )
        )
        if not stop_event.wait(timeout=TIMEOUT_FOR_STOP_DAEMON):
            raise RuntimeError("Impossible to shutdown the sandbox")


def get_token() -> str:
    """
    Gets the security token of the current daemon.

    Returns:
        The security token as a string.

    Raises:
        AssertionError: If the daemon is not started.
    """
    global _current_daemon
    assert _current_daemon
    return _current_daemon.token


async def async_call_in_sandbox(
    func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """
    Asynchronously executes a function inside the sandbox.

    If the call is already inside a sandbox, it executes the function directly.
    Otherwise, it forwards the call to the current daemon.

    Args:
        func: The function to execute.
        *args: Positional arguments for the function.
        **kwargs: Keyword arguments for the function.

    Returns:
        The result of the function execution.

    Raises:
        AssertionError: If the daemon is not started.
    """
    global _current_daemon
    if is_in_sandbox():
        return await func(*args, **kwargs)

    assert _current_daemon is not None, "Daemon not started"
    return await _current_daemon.async_call_in_sandbox(func, False, *args, **kwargs)


def call_in_sandbox(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Synchronously executes a function inside the sandbox.

    If the call is already inside a sandbox, it executes the function directly.
    Otherwise, it forwards the call to the current daemon.

    Args:
        func: The function to execute.
        *args: Positional arguments for the function.
        **kwargs: Keyword arguments for the function.

    Returns:
        The result of the function execution.

    Raises:
        AssertionError: If the daemon is not started.
    """
    global _current_daemon
    if is_in_sandbox():
        return func(*args, **kwargs)
    assert _current_daemon is not None, (
        "Daemon not started. Use 'with sandboxes()' " "or 'pysandboxes.run()'"
    )
    check_mixte_async_async()

    return _current_daemon.call_in_sandbox(func, False, *args, **kwargs)
