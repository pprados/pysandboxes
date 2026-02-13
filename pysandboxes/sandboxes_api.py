import asyncio
import functools
import inspect
import logging
import os
import signal
import threading
from multiprocessing import Lock
from pathlib import Path
from typing import Any, TypeVar, Union, \
    Coroutine, runtime_checkable, List, Protocol, Dict
from typing import Callable, Optional

from .base_daemon import BaseDaemon
from .e import ConfigSyntaxError
from .os_sandbox import async_shutdown_daemon
from .private_loop import set_sandbox_loop, sandbox_loop
from .tools import check_mixte_async_async, SyncOrAsyncFunc, set_is_in_sandbox, \
    is_in_sandbox

logger = logging.getLogger(__name__)

_lock = Lock()

F = TypeVar("F", bound=Callable[..., Any])


def _check__main__coroutine(coroutine):
    if inspect.getmodule(coroutine.cr_frame).__name__ == "__main__":
        raise ValueError("The coroutine must be declared in a module "
                         "other than __main__.")


def sandbox(_func: Optional[F] = None,
            ) -> Callable[..., Any]:
    """
    Decorator to run a function in a sandbox.y
    The function can be either synchronous or asynchronous.
    Reraises any exception raised by the function.
    """
    from pysandboxes.os_sandbox import call_in_sandbox, async_call_in_sandbox

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await async_call_in_sandbox(func, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return call_in_sandbox(func, *args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)


@runtime_checkable
class sandboxes(Protocol):
    __slot__ = (
        'init_fn',
        'config_path',
        'envs',
        'extra_rules',
        'learning_path',
        'python_args',
        "_old_sigint"
        "_old_sigterm"
        "_old_sigquit"
        "_daemon"
    )
    """
    Context manager to start and stop the sandbox daemon.
    The parameter `init_fn` is a function that will be called when the daemon starts,
    inside the daemon process. It's a good place to initialize the database connection,
    or to load some data.
    """

    def __init__(self,
                 init_fn: Optional[SyncOrAsyncFunc] = None,
                 config_path: Optional[Union[Path, str]] = None,
                 *,
                 envs: Optional[Dict[str, str]] = None,
                 python_args: Optional[List[str]] = None,
                 **extra_rules,
                 ) -> None:
        self.init_fn = init_fn
        self.config_path = (
            config_path if isinstance(config_path, Path)
            else Path(config_path) if config_path else None
        )
        if envs is None:
            envs = os.environ
        self.envs = envs
        self.extra_rules = extra_rules
        self.learning_path = None
        self.python_args = python_args
        self._old_sigint = None
        self._old_sigterm = None
        self._old_sigquit = None
        self._daemon = None

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> BaseDaemon:
        """
        Start the sandbox daemon.
        """
        from .py_sandbox import load_and_parse_config
        from .os_sandbox import start_daemon
        from .e import ConfigSyntaxError


        if not is_in_sandbox():  # Inner call
            check_mixte_async_async()
            log_level = logging.root.getEffectiveLevel()
            try:
                all_rules = load_and_parse_config(
                    config_path=self.config_path,
                    envs=self.envs,
                    **self.extra_rules,
                )
            except ConfigSyntaxError as e:
                raise e.with_traceback(None)
            self._daemon = start_daemon(all_rules,
                                        envs=self.envs,
                                        log_level=log_level,
                                        init_fn=self.init_fn,
                                        python_args=self.python_args,
                                        )
            self.learning_path = all_rules.learning_path

            def signal_handler(signum: int, frame: object) -> None:
                """
                Handles termination signa8ls (SIGINT, SIGTERM) for the parent process.
                It will kill daemon processes before exiting itself.
                """
                # Iterate through all child processes and send them SIGTERM
                logger.debug("Catch signal %s. Propagate to the dameon.", signum)
                self._stop_daemon()

            if threading.current_thread() is threading.main_thread():
                self._old_sigint = signal.signal(signal.SIGINT, signal_handler)
                self._old_sigterm = signal.signal(signal.SIGTERM, signal_handler)
                self._old_sigquit = signal.signal(signal.SIGQUIT, signal_handler)

        return self._daemon


    def __exit__(self,
                 exc_type: Optional[type[BaseException]],
                 exc: Optional[BaseException],
                 tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        logger.debug("__exit__ start...")
        if is_in_sandbox():
            set_is_in_sandbox(False)
            return False
        self._stop_daemon()
        return False

    async def _stop_daemon(self):
        if self._daemon:
            from pysandboxes.os_sandbox import shutdown_daemon
            logger.debug("_stop_daemon...")

            if threading.current_thread() is threading.main_thread():
                # Restore signal handler
                signal.signal(signal.SIGINT, self._old_sigint)
                signal.signal(signal.SIGTERM, self._old_sigterm)
                signal.signal(signal.SIGQUIT, self._old_sigquit)

            self._daemon = None
            self.learning_path = False
            await async_shutdown_daemon()
            logger.debug("daemon stopped")

    def __delete__(self, instance):
        self._stop_daemon()  # FIXME: ne fonctionne pas en async

    # ── asynchronous API ───────────────────────────────
    async def __aenter__(self) -> BaseDaemon:  # FIXME: compare avec enter() et TU
        """
        Start the sandbox daemon.
        """
        if not is_in_sandbox():
            from .py_sandbox import load_and_parse_config
            from pysandboxes.os_sandbox import async_start_daemon
            log_level = logging.root.getEffectiveLevel()
            try:
                all_rules = load_and_parse_config(
                    self.config_path,
                    envs=self.envs,
                    **self.extra_rules,
                )
            except ConfigSyntaxError as e:
                raise e.with_traceback(None)
            self._daemon = await async_start_daemon(
                all_rules,
                envs=self.envs,
                log_level=log_level,
                init_fn=self.init_fn)
            self.learning_path = all_rules.learning_path

            def signal_handler(signum: int, frame: object) -> None:
                """
                Handles termination signa8ls (SIGINT, SIGTERM) for the parent process.
                It will kill daemon processes before exiting itself.
                """
                # Iterate through all child processes and send them SIGTERM
                logger.debug("Catch signal %s. Propagate to the dameon.", signum)
                asyncio.get_running_loop().create_task(
                    self._stop_daemon()
                )

            if threading.current_thread() is threading.main_thread():
                self._old_sigint = signal.signal(signal.SIGINT, signal_handler)
                self._old_sigterm = signal.signal(signal.SIGTERM, signal_handler)
                self._old_sigquit = signal.signal(signal.SIGQUIT, signal_handler)
        return self._daemon

    @sandbox_loop
    async def __aexit__(self,
                        exc_type: Optional[type[BaseException]],
                        exc: Optional[BaseException],
                        tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        if not is_in_sandbox() and self._daemon:
            from pysandboxes.os_sandbox import async_shutdown_daemon
            await async_shutdown_daemon()
        return False


def run(main: Coroutine[Any, Any, Any],
        *, debug=None, loop_factory=None,
        init_fn: Optional[SyncOrAsyncFunc] = None,
        config_path: Optional[Union[Path, str]] = None,
        **kwargs: Any) -> Any:
    """
    Run the main coroutine in a new event loop, with the sandbox
    It's similar to `asyncio.run()`, but with the sandbox.
    The parameters are the same as `asyncio.run()`.
    """
    _check__main__coroutine(main)

    async def _run():
        # In this context, use the standard running loop.
        # the sandbox will be started before the main coroutine.
        # loop = asyncio.get_running_loop()
        set_sandbox_loop(asyncio.get_running_loop())
        async with sandboxes(
                init_fn=init_fn,
                config_path=config_path,
                **kwargs,
        ):
            result = (await asyncio.create_task(main), "start sandbox in run")
            return result

    result = asyncio.run(_run())
    return result
