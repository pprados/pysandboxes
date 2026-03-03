# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Sandbox API module providing decorators and context managers.

This module contains the main public API for PySandboxes, including:
- @sandbox decorator for function-level sandboxing
- sandboxes() context manager for process-level sandboxing
- run() function for running coroutines in sandboxes
- Utility functions for sandbox state management

The API supports both synchronous and asynchronous usage patterns and provides
automatic lifecycle management for sandbox processes.
"""

import asyncio
import functools
import inspect
import logging
import os
import signal
import threading
from multiprocessing import Lock
from pathlib import Path
from types import FrameType
from typing import (
    Any,
    Callable,
    Coroutine,
    TypeVar,
)

from .base_daemon import BaseDaemon, FakeDaemon
from .e import ConfigSyntaxError
from .learning import generate_config_from_learning
from .os_sandbox import async_shutdown_daemon
from .private_loop import get_sandbox_loop, sandbox_loop, set_sandbox_loop
from .tools import (
    Environ,
    SyncOrAsyncFunc,
    check_mixte_async_async,
    is_in_sandbox,
    set_is_in_sandbox,
)

logger = logging.getLogger(__name__)

_lock = Lock()

F = TypeVar("F", bound=Callable[..., Any])


def _check__main__coroutine(coroutine: Any) -> None:
    """Check that a coroutine is not defined in __main__ module.

    Args:
        coroutine: The coroutine to check.

    Raises:
        ValueError: If the coroutine is defined in __main__ module.
    """
    module = inspect.getmodule(coroutine.cr_frame)
    if module and hasattr(module, "__name__"):
        if module.__name__ == "__main__":
            raise ValueError(
                "The coroutine must be declared in a module " "other than __main__."
            )


def sandbox(
    _func: F | None = None,
) -> Callable[..., Any]:
    """Decorator to run a function in a sandbox.

    This decorator can be applied to both synchronous and asynchronous functions.
    The decorated function will execute in an isolated sandbox environment with
    restricted access to system resources.

    Args:
        _func: The function to be decorated (used when decorator is called
        without parentheses).

    Returns:
        The decorated function that will run in a sandbox.

    Raises:
        Any exception raised by the original function is re-raised.

    Examples:
        Decorating a synchronous function:
        ```python
        @sandbox
        def safe_calculation(x, y):
            return x + y
        ```

        Decorating an asynchronous function:
        ```python
        @sandbox
        async def async_task():
            return await some_operation()
        ```
    """
    from pysandboxes.os_sandbox import async_call_in_sandbox, call_in_sandbox

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await async_call_in_sandbox(func, *args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return call_in_sandbox(func, *args, **kwargs)

            return sync_wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)


_SIGNAL_HANDLER = Callable[[int, FrameType | None], Any] | int | signal.Handlers | None


class sandboxes:
    """Context manager for sandbox process lifecycle management.

    This class provides both synchronous and asynchronous context manager interfaces
    for managing sandbox processes. It handles daemon startup, configuration, and
    graceful shutdown.

    Attributes:
        init_fn: Optional initialization function called when daemon starts.
        sandboxes_config: Path to sandbox configuration file.
        envs: Environment variables available in the sandbox.
        extra_rules: Additional security rules to apply.
        learning_path: Path for learning mode rule generation.
        python_args: Additional Python interpreter arguments.
        graceful_shutdown: Whether to shutdown gracefully on exit.

    Examples:
        Basic usage:
        ```python
        with sandboxes():
            # Code runs in sandbox
            result = some_function()
        ```

        With custom configuration:
        ```python
        with sandboxes(pysandboxes_config="custom.conf", graceful_shutdown=True):
            result = some_function()
        ```

        Async usage:
        ```python
        async with sandboxes():
            result = await some_async_function()
        ```
    """

    __slots__ = (
        "init_fn",
        "sandboxes_config",
        "envs",
        "extra_rules",
        "learning_path",
        "python_args",
        "graceful_shutdown",
        "_signals",
        "_daemon",
    )

    def __init__(
        self,
        init_fn: SyncOrAsyncFunc | None = None,
        sandboxes_config: Path | str | None = None,
        *,
        envs: Environ | None = None,
        python_args: list[str] | None = None,
        graceful_shutdown: bool = True,
        **extra_rules: dict[str, Any],
    ) -> None:
        """Initialize the sandbox context manager.

        Args:
            init_fn: Function called during daemon initialization in
            the sandbox process.
            sandboxes_config: Path to configuration file or directory.
            envs: Environment variables to make available in sandbox.
            python_args: Additional arguments for Python interpreter.
            graceful_shutdown: Whether to shutdown gracefully on exit.
            **extra_rules: Additional security rules as keyword arguments.
        """
        self.init_fn = init_fn
        self.sandboxes_config = (
            sandboxes_config
            if isinstance(sandboxes_config, Path)
            else Path(sandboxes_config) if sandboxes_config else None
        )
        if envs is None:
            envs = os.environ
        self.envs = envs
        self.extra_rules = extra_rules
        self.learning_path: Path | None = None
        self.python_args = python_args
        self.graceful_shutdown = graceful_shutdown
        self._signals: dict[int, _SIGNAL_HANDLER] = {}

        self._daemon: BaseDaemon | None = None

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> BaseDaemon:
        """Start the sandbox daemon for synchronous context manager.

        Returns:
            The started daemon instance.

        Raises:
            ConfigSyntaxError: If the configuration file has syntax errors.
        """
        from .e import ConfigSyntaxError
        from .os_sandbox import start_daemon
        from .py_sandbox import load_and_parse_config

        if not is_in_sandbox():  # Inner call
            check_mixte_async_async()
            log_level = logging.root.getEffectiveLevel()
            try:
                all_rules = load_and_parse_config(
                    config_path=self.sandboxes_config,
                    envs=self.envs,
                    **self.extra_rules,
                )
            except ConfigSyntaxError as e:
                raise e.with_traceback(None)
            self._daemon = start_daemon(
                all_rules,
                envs=self.envs,
                log_level=log_level,
                init_fn=self.init_fn,
                python_args=self.python_args,
            )
            self.learning_path = all_rules.learning_path

            def signal_handler(signum: int, frame: FrameType | None) -> None:
                """
                Handles termination signa8ls (SIGINT, SIGTERM) for the parent process.
                It will kill daemon processes before exiting itself.
                """
                # Iterate through all child processes and send them SIGTERM
                logger.debug("Catch signal %s. Propagate to the daemon.", signum)
                # Remove this handler
                signal.signal(
                    signum, self._signals[signum]
                )
                loop = get_sandbox_loop()

                async def _stop_and_propagate_signal():
                    await self._stop_daemon()
                    import _thread
                    logger.debug("Propagate {%i}",signum)
                    _thread.interrupt_main(signum)

                loop.call_soon_threadsafe(lambda: loop.create_task(_stop_and_propagate_signal()))

            if threading.current_thread() is threading.main_thread():
                logger.debug("Activate signal handlers.")
                self._signals[signal.SIGINT] = signal.signal(
                    signal.SIGINT, signal_handler
                )
                self._signals[signal.SIGTERM] = signal.signal(
                    signal.SIGTERM, signal_handler
                )
                self._signals[signal.SIGQUIT] = signal.signal(
                    signal.SIGQUIT, signal_handler
                )
        else:
            self._daemon = FakeDaemon(token="Fake token")
        assert self._daemon is not None
        return self._daemon

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> None:
        """
        Stop the sandbox daemon.
        """
        logger.debug("__exit__ _start...")
        if is_in_sandbox():
            set_is_in_sandbox(False)
            return

        asyncio.run_coroutine_threadsafe(
            async_shutdown_daemon(self.graceful_shutdown), get_sandbox_loop()
        ).result()
        return

    async def _stop_daemon(self) -> None:
        if self._daemon and self._daemon.is_started:
            logger.debug("_stop_daemon...")
            if threading.current_thread() is threading.main_thread():
                # Restore signal handler
                signal.signal(signal.SIGINT, self._signals[signal.SIGINT])
                signal.signal(signal.SIGTERM, self._signals[signal.SIGTERM])
                signal.signal(signal.SIGQUIT, self._signals[signal.SIGQUIT])

            # await self._daemon._stop(max_pending=0)
            await self._daemon._shutdown()
            logger.debug("daemon shutdowned")

    def __delete__(self, instance: "sandboxes") -> None:
        asyncio.run_coroutine_threadsafe(
            self._stop_daemon(), get_sandbox_loop()
        ).result()

    # ── asynchronous API ───────────────────────────────
    async def __aenter__(self) -> BaseDaemon:
        """
        Start the sandbox daemon.
        """
        if not is_in_sandbox():
            from pysandboxes.os_sandbox import async_start_daemon

            from .py_sandbox import load_and_parse_config

            log_level = logging.root.getEffectiveLevel()
            try:
                all_rules = load_and_parse_config(
                    self.sandboxes_config,
                    envs=self.envs,
                    **self.extra_rules,
                )
            except ConfigSyntaxError as e:
                raise e.with_traceback(None)
            self._daemon = await async_start_daemon(
                all_rules, envs=self.envs, log_level=log_level, init_fn=self.init_fn
            )
            self.learning_path = all_rules.learning_path

            def signal_handler(signum: int, frame: object) -> None:
                """
                Handles termination signa8ls (SIGINT, SIGTERM) for the parent process.
                It will kill daemon processes before exiting itself.
                """
                # Iterate through all child processes and send them SIGTERM
                logger.debug("Catch signal %s. Propagate to the daemon.", signum)

                asyncio.get_running_loop().create_task(self._stop_daemon())
                handler = self._signals[signum]
                if isinstance(handler, Callable):
                    handler(signum, frame)

            if threading.current_thread() is threading.main_thread():
                logger.debug("Activate signal handlers.")
                self._signals[signal.SIGINT] = signal.signal(
                    signal.SIGINT, signal_handler
                )
                self._signals[signal.SIGTERM] = signal.signal(
                    signal.SIGTERM, signal_handler
                )
                self._signals[signal.SIGQUIT] = signal.signal(
                    signal.SIGQUIT, signal_handler
                )
        assert self._daemon is not None
        return self._daemon

    @sandbox_loop
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        """
        Stop the sandbox daemon.
        """
        if not is_in_sandbox() and self._daemon:
            await async_shutdown_daemon(self.graceful_shutdown)
        return False


def run(
    main: Coroutine[Any, Any, Any],  # TODO: accept function without parameter
    *,
    init_fn: SyncOrAsyncFunc | None = None,
    config_path: Path | str | None = None,
    envs: Environ | None = None,
    python_args: list[str] | None = None,
    graceful_shutdown: bool = True,
    **kwargs: dict[str, Any],
) -> Any:
    """
    Run the main coroutine in a new event loop, with the sandbox
    It's similar to `asyncio.run()`, but with the sandbox.
    The parameters are the same as `asyncio.run()`.
    """

    # FIXME _check__main__coroutine(main)

    async def _run() -> Any:
        # In this context, use the standard running loop.
        # the sandbox will be started before the main coroutine.
        # loop = asyncio.get_running_loop()
        set_sandbox_loop(asyncio.get_running_loop())
        async with sandboxes(
            init_fn=init_fn,
            sandboxes_config=config_path,
            envs=envs,
            python_args=python_args,
            graceful_shutdown=graceful_shutdown,
            **kwargs,
        ):
            result = (await asyncio.create_task(main), "_start sandbox in run")
            return result

    if not inspect.iscoroutine(main):
        raise ValueError("a coroutine was expected, got {!r}".format(main))
    result = asyncio.run(_run())
    return result
