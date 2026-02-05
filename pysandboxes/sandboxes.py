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
from .os_sandbox import shutdown_daemon
from .private_loop import set_sandbox_loop
from .py_sandbox import ConfigSyntaxError
from .remote.parameters import DELAY_FOR_CALL_DAEMON
from .tools import check_mixte_async_async, SyncOrAsyncFunc
from .types import Envs

logger = logging.getLogger(__name__)

_lock = Lock()

F = TypeVar("F", bound=Callable[..., Any])


def sandbox(_func: Optional[F] = None, *,
            timeout: float = DELAY_FOR_CALL_DAEMON) -> Callable[..., Any]:
    """
    Decorator to run a function in a sandbox.y
    The function can be either synchronous or asynchronous.
    The timeout parameter is used to set the maximum execution time of the function.
    Raises a TimeoutError if the function execution exceeds the timeout.
    Return the result of the function if it completes within the timeout.
    Reraises any exception raised by the function.
    """
    from pysandboxes.os_sandbox import call_in_sandbox, async_call_in_sandbox

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await async_call_in_sandbox(func, timeout, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return call_in_sandbox(func, timeout, *args, **kwargs)

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
    __slot__=(
        'init_fn',
        'config_path',
        'envs',
        'extra_rules',
        'timeout',
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
                 extra_rules: Optional[List[str]] = None,
                 ) -> None:
        self.init_fn = init_fn
        self.config_path = config_path
        if envs is None:
            envs = os.environ
        self.envs = Envs(envs)
        self.extra_rules = extra_rules
        self.timeout = 60  # FIXME: timeout=60
        self._old_sigint = None
        self._old_sigterm = None

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> None:
        """
        Start the sandbox daemon.
        """
        from .py_sandbox import read_and_parse_config
        from .os_sandbox import start_daemon

        logger.debug("__enter__ start...")
        check_mixte_async_async()
        log_level = logging.root.getEffectiveLevel()
        try:
            all_rules = read_and_parse_config(
                self.config_path,
                envs=self.envs,
                extra_rules=self.extra_rules,
            )
        except ConfigSyntaxError as e:
            raise e.with_traceback(None)
        start_daemon(all_rules,
                     log_level=log_level,
                     init_fn=self.init_fn,
                     timeout=self.timeout,
                     )

        def signal_handler(signum: int, frame: object) -> None:
            """
            Handles termination signals (SIGINT, SIGTERM) for the parent process.
            It will kill daemon processes before exiting itself.
            """
            # Iterate through all child processes and send them SIGTERM
            logger.debug("Catch signal %s. Propagate to the dameon.", signum)
            shutdown_daemon()

        if threading.current_thread() is threading.main_thread():
            self._old_sigint = signal.signal(signal.SIGINT, signal_handler)
            self._old_sigterm = signal.signal(signal.SIGTERM, signal_handler)
        logger.debug("__enter__ ok")

    def __exit__(self,
                 exc_type: Optional[type[BaseException]],
                 exc: Optional[BaseException],
                 tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        from pysandboxes.os_sandbox import shutdown_daemon
        logger.debug("__exit__ start...")
        # If "Cannot call the synchronize sandbox function from another sandbox async function"
        if not isinstance(exc, RuntimeError):
            shutdown_daemon()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._old_sigint)
            signal.signal(signal.SIGTERM, self._old_sigterm)

        logger.debug("__exit__ done")
        return False

    # ── asynchronous API ───────────────────────────────
    async def __aenter__(self) -> BaseDaemon:
        """
        Start the sandbox daemon.
        """
        from .py_sandbox import read_and_parse_config
        from pysandboxes.os_sandbox import async_start_daemon
        log_level = logging.root.getEffectiveLevel()
        all_rules = read_and_parse_config(
            self.config_path,
            envs=self.envs,
            extra_rules=self.extra_rules,
            exit_on_error=False,
        )
        return await async_start_daemon(
            all_rules,
            log_level=log_level,
            init_fn=self.init_fn)

    async def __aexit__(self,
                        exc_type: Optional[type[BaseException]],
                        exc: Optional[BaseException],
                        tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        from pysandboxes.os_sandbox import async_shutdown_daemon
        await async_shutdown_daemon()
        return False


def run(main: Coroutine[Any, Any, Any],
        *, debug=None, loop_factory=None,
        init_fn: Optional[SyncOrAsyncFunc] = None,
        config_path: Optional[Union[Path, str]] = None) -> Any:
    """
    Run the main coroutine in a new event loop, with the sandbox
    It's similar to `asyncio.run()`, but with the sandbox.
    The parameters are the same as `asyncio.run()`.
    """

    async def _run():
        # In this context, use the standard running loop.
        # the sandbox will be started before the main coroutine.
        # loop = asyncio.get_running_loop()
        set_sandbox_loop(asyncio.get_running_loop())
        async with sandboxes(
                init_fn=init_fn,
                config_path=config_path
        ):
            result = (await asyncio.create_task(main), "start sandbox in run")
            return result

    result = asyncio.run(_run())
    return result
