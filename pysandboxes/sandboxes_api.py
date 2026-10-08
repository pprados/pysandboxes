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
import importlib
import inspect
import logging
import os
import signal
import threading
from pathlib import Path
from types import FrameType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    ParamSpec,
    TypeVar,
    overload,
)

from ._os_sandbox import async_shutdown_daemon
from .base_daemon import BaseDaemon, FakeDaemon
from .e import ConfigSyntaxError
from .private_loop import get_sandbox_loop, sandbox_loop, set_sandbox_loop
from .tools import (
    Environ,
    SyncOrAsyncFunc,
    check_mixte_async_async,
    is_in_sandbox,
)

if TYPE_CHECKING:
    from .all_rules import AllRules

logger = logging.getLogger(__name__)

# Loaded before any sandbox arms, without creating a lock: arming hands a module already loaded back as it is,
# and the learned profiles never list what multiprocessing imports for itself (_weakrefset, _pickle...). A call,
# not an import statement, so that no unused-import cleanup can remove it; test_sandboxes_api.py pins it.
importlib.import_module("multiprocessing.synchronize")


def _refuse_locked_extra_rules(all_rules: "AllRules", extra_rules: dict[str, Any]) -> None:
    """Refuse the directives given to the API when the rule file holds `learn=false`.

    Raises:
        ConfigSyntaxError: If `extra_rules` is not empty and the rules are locked.
    """
    from .guard_provider import learn_lock
    from .main_logger import format_ruleref

    if extra_rules and (lock := learn_lock(all_rules.config)):
        raise ConfigSyntaxError(
            "Syntax error in config files.",
            [
                f"{format_ruleref(lock)}: {lock.rule!r} locks the rules, the API cannot add "
                f"{', '.join(sorted(extra_rules))}"
            ],
        )


_P = ParamSpec("_P")
_R = TypeVar("_R")


@overload
def sandbox(_func: Callable[_P, Coroutine[Any, Any, _R]]) -> Callable[_P, Coroutine[Any, Any, _R]]: ...
@overload
def sandbox(_func: Callable[_P, _R]) -> Callable[_P, _R]: ...
@overload
def sandbox(_func: None = None) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]: ...
def sandbox(
    _func: Callable[..., Any] | None = None,
) -> Any:
    """Decorator to run a function in a sandbox.

    This decorator can be applied to both synchronous and asynchronous functions.
    The decorated function will execute in an isolated sandbox environment with
    restricted access to system resources. It keeps the decorated function's
    signature for type checkers.

    A method decorated with ``@sandbox`` is sent to the sandboxed child the same
    way a plain function is: by reference, resolved there through its module and
    qualified name. It works for a method of a class defined in an importable
    module, but not for one defined interactively or in ``__main__``, which the
    child cannot import back; this is the same restriction `multiprocessing`
    places on its own targets.

    Args:
        _func: The function to be decorated (used when decorator is called
        without parentheses).

    Returns:
        The decorated function that will run in a sandbox.

    Raises:
        TypeError: If `_func` is a generator or asynchronous generator function;
            neither can be sent across the sandbox boundary.
        Any exception raised by the original function is re-raised.

    Return value:
        The value travels back from the sandboxed child as a pickle the parent
        decodes, and the child may be hostile. Two profile rules choose how:

        - ``remote-result-mode=data-only`` (default): values only. ``None``,
          ``bool``, ``int``, ``float``, ``complex``, ``str``, ``bytes``,
          ``bytearray``, ``list``, ``tuple``, ``dict``, ``set``, ``frozenset``,
          ``OrderedDict``, ``Counter``, ``deque``, without cycles, and the value
          classes they may hold: ``pathlib`` paths, ``datetime`` dates, times,
          durations and time zones (``timezone``, ``zoneinfo.ZoneInfo``),
          ``time.struct_time``, ``decimal.Decimal``, ``fractions.Fraction``,
          ``uuid.UUID``, ``ipaddress`` addresses, networks and interfaces, and
          ``range``. A closed list: anything else is refused, and no code of the
          stream's choosing runs in the parent.
        - ``remote-result-mode=objects``: any picklable value. Objects are
          rebuilt, and a denylist refuses the classes and functions that act when
          called in the parent: processes, files (``shutil``, ``io``,
          ``tempfile``, ``logging``...), signals, ``pickle``, ``types``, methods
          reached through a dotted name. The denylist is not exhaustive. Learning
          mode writes this rule, with a warning, when it sees an object returned.
        - ``remote-result-guard=false``: removes the denylist from the
          ``objects`` mode. The opcode check and the exception guard remain.
          Use it only when the child is trusted.

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
    from pysandboxes._os_sandbox import async_call_in_sandbox, call_in_sandbox

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
            raise TypeError(
                f"@sandbox cannot decorate {func.__qualname__!r}: generator and asynchronous "
                "generator functions cannot be sent across the sandbox boundary."
            )

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
        graceful_shutdown: Whether to shut down gracefully on exit.

    Examples:
        Basic usage:
        ```python
        with sandboxes():
            # Only @sandbox-decorated calls made in this block run in the sandbox.
            result = some_function()
        ```

        With custom configuration:
        ```python
        with sandboxes(sandboxes_config="custom.conf", graceful_shutdown=True):
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
        "_lock",
    )

    def _register_signals_handlers(self) -> None:
        with self._lock:
            # Windows has no SIGQUIT
            register_signal = tuple(
                getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGQUIT") if hasattr(signal, name)
            )

            self._signals: dict[signal.Signals, Any | int | signal.Handlers | None] = {
                s: signal.getsignal(s) for s in register_signal
            }

            def signal_handler(
                signum: int,
                frame: FrameType | None,
            ) -> Any | int | signal.Handlers:
                """
                Handles termination signals for the parent process.
                Restores the previous handler, then applies it. A default disposition
                first stops the daemon, then lets the signal terminate the process.
                """
                # Iterate through all child processes and send them SIGTERM
                logger.debug("with sandboxes(): Catch signal %s.", signum)
                _no_val = object()
                handler = self._signals.pop(signal.Signals(signum), _no_val)
                if handler is _no_val:
                    return _no_val
                signal.signal(signum, handler)  # Remove myself

                if callable(handler):
                    if threading.current_thread() != threading.main_thread():
                        import _thread

                        _thread.interrupt_main(signal.Signals(signum))
                    else:
                        return handler(signum, frame)
                elif handler == signal.SIG_DFL:
                    if not is_in_sandbox():
                        asyncio.run_coroutine_threadsafe(self._stop_daemon(), get_sandbox_loop()).result()
                    signal.raise_signal(signum)
                return None

            for s in self._signals.keys():
                signal.signal(signal.Signals(s), signal_handler)

    def _unregister_signals_handlers(self) -> None:
        with self._lock:
            # If used private a private loop, the signal will be removed if it's handle
            if threading.current_thread() is threading.main_thread():
                for s, h in self._signals.items():
                    signal.signal(s, h)
            else:
                logging.info("Impossible to remove signals")
                pass
            self._signals.clear()

    def __init__(
        self,
        init_fn: SyncOrAsyncFunc | None = None,
        sandboxes_config: Path | str | None = None,
        *,
        envs: Environ | None = None,
        python_args: list[str] | None = None,
        graceful_shutdown: bool = True,
        **extra_rules: Any,
    ) -> None:
        """Initialize the sandbox context manager.

        Args:
            init_fn: Function called during daemon initialization in
            the sandbox process.
            sandboxes_config: Path to configuration file or directory.
            envs: Environment variables to make available in sandbox.
            python_args: Additional arguments for Python interpreter.
            graceful_shutdown: Whether to shut down gracefully on exit.
            **extra_rules: Configuration directives, added in front of those of the configuration file. The
                keyword is the directive with its dashes written as underscores, the value is the directive's
                value, or a `list`, `tuple`, `set` or `frozenset` of values for a directive that repeats:
                `learn=".py-sandboxes"` starts the learning mode and writes the rules it discovers to that
                file, `os_sandbox="bwrap"` selects the OS provider, `py_sandbox="true"` arms the Python layer.
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
        self.extra_rules: dict[str, Any] = {
            k: set(v) if isinstance(v, (list, tuple, frozenset)) else v for k, v in extra_rules.items()
        }
        self.learning_path: Path | None = None
        self.python_args = python_args
        self.graceful_shutdown = graceful_shutdown

        self._daemon: BaseDaemon | None = None
        self._lock = threading.Lock()

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> BaseDaemon:
        """Start the sandbox daemon for synchronous context manager.

        Returns:
            The started daemon instance.

        Raises:
            ConfigSyntaxError: If the configuration file has syntax errors.
        """
        from ._os_sandbox import start_daemon
        from .e import ConfigSyntaxError
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
                raise e.with_traceback(None) from e
            _refuse_locked_extra_rules(all_rules, self.extra_rules)
            self._daemon = start_daemon(
                all_rules,
                envs=self.envs,
                log_level=log_level,
                init_fn=self.init_fn,
                python_args=self.python_args,
            )
            self.learning_path = all_rules.learning_path
        else:
            self._daemon = FakeDaemon(token="Fake token")
        assert self._daemon is not None
        self._register_signals_handlers()
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
        self._unregister_signals_handlers()
        if not is_in_sandbox():
            asyncio.run_coroutine_threadsafe(self._stop_daemon(), get_sandbox_loop()).result()
        self._daemon = None
        return

    async def _stop_daemon(self) -> bool:
        if self._daemon and self._daemon.is_started:
            if self._daemon:
                self._daemon = None
                await async_shutdown_daemon(self.graceful_shutdown)
                logger.debug("daemon stopped")
        return True

    # ── asynchronous API ───────────────────────────────
    async def __aenter__(self) -> BaseDaemon:
        """
        Start the sandbox daemon.
        """
        if not is_in_sandbox():
            from pysandboxes._os_sandbox import async_start_daemon

            from .py_sandbox import load_and_parse_config

            log_level = logging.root.getEffectiveLevel()
            try:
                all_rules = await asyncio.to_thread(
                    load_and_parse_config,
                    self.sandboxes_config,
                    envs=self.envs,
                    **self.extra_rules,
                )
            except ConfigSyntaxError as e:
                raise e.with_traceback(None) from e
            _refuse_locked_extra_rules(all_rules, self.extra_rules)
            self._daemon = await async_start_daemon(
                all_rules,
                envs=self.envs,
                log_level=log_level,
                init_fn=self.init_fn,
                python_args=self.python_args,
            )
            self.learning_path = all_rules.learning_path

        else:
            self._daemon = FakeDaemon(token="Fake token")
        assert self._daemon is not None
        self._register_signals_handlers()
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
        self._unregister_signals_handlers()
        if not is_in_sandbox():
            await self._stop_daemon()
        self._daemon = None
        return False


def run(
    main: Coroutine[Any, Any, Any],  # TODO: accept function without parameter
    *,
    init_fn: SyncOrAsyncFunc | None = None,
    sandboxes_config: Path | str | None = None,
    envs: Environ | None = None,
    python_args: list[str] | None = None,
    graceful_shutdown: bool = True,
    **extra_rules: Any,
) -> Any:
    """Run a coroutine in a new event loop, with the sandbox started around it.

    Plays the role `asyncio.run()` plays for plain code: it owns the loop for
    the duration of the call. The sandbox is armed before ``main`` is scheduled
    and shut down once it returns, so the coroutine never observes an
    unprotected interpreter. The keyword arguments are those of `sandboxes`,
    not those of `asyncio.run()`.

    Args:
        main: The coroutine to run. A coroutine object is expected, not the
            function that produces one.
        init_fn: Function called during daemon initialization in the sandbox
            process.
        sandboxes_config: Path to the configuration file or directory.
        envs: Environment variables to make available in the sandbox.
        python_args: Additional arguments for the Python interpreter.
        graceful_shutdown: Whether to shut down gracefully on exit.
        **extra_rules: Configuration directives, passed on to `sandboxes`: `learn=".py-sandboxes"` starts the
            learning mode, `os_sandbox="bwrap"` selects the OS provider, `py_sandbox="true"` arms the Python
            layer.

    Returns:
        Whatever ``main`` returns.

    Raises:
        ValueError: If ``main`` is not a coroutine.

    Examples:
        ```python
        async def job():
            return 42

        run(job())
        ```
    """

    async def _run() -> Any:
        # In this context, use the standard running loop.
        # the sandbox will be started before the main coroutine.
        # loop = asyncio.get_running_loop()
        set_sandbox_loop(asyncio.get_running_loop())
        async with sandboxes(
            init_fn=init_fn,
            sandboxes_config=sandboxes_config,
            envs=envs,
            python_args=python_args,
            graceful_shutdown=graceful_shutdown,
            **extra_rules,
        ):
            return await asyncio.create_task(main)

    if not inspect.iscoroutine(main):
        raise ValueError("a coroutine was expected, got {!r}".format(main))
    result = asyncio.run(_run())
    return result
