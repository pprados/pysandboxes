import asyncio
import functools
import inspect
import logging
import signal
from multiprocessing import Lock
from pathlib import Path
from typing import Any, TypeVar, Union, \
    Awaitable, Coroutine
from typing import Callable, Optional

from .py_sandbox import get_config_path, read_and_parse_config
from .remote.base_daemon import BaseDaemon, _mixed_sync_and_async_error
from .remote.manage_loop import set_sandbox_loop, get_sandbox_loop, reset_sandbox_loop
from .remote.os_sandboxes import shutdown_daemon, _async_start_daemon, \
    is_daemon_started, async_start_daemon, _check_mixte_async_async

logger = logging.getLogger(__name__)

_lock = Lock()

F = TypeVar("F", bound=Callable[..., Any])


# TODO: ajouter le max de TU
def sandbox(_func: Optional[F] = None, *, timeout: float = 0) -> Callable[..., Any]:
    """
    Decorator to run a function in a sandbox.y
    The function can be either synchronous or asynchronous.
    The timeout parameter is used to set the maximum execution time of the function.
    Raises a TimeoutError if the function execution exceeds the timeout.
    Return the result of the function if it completes within the timeout.
    Reraises any exception raised by the function.
    """
    from .remote.os_sandboxes import call_in_sandbox, async_call_in_sandbox

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


SyncOrAsyncFunc = Union[
    Callable[[], None],  # Fonction synchrone
    Callable[[], Awaitable[None]]  # Fonction asynchrone
]


# Define a signal handler function
# def signal_handler(signum: int, frame: object) -> None:
#     """
#     Handles termination signals (SIGINT, SIGTERM) for the parent process.
#     It will kill all child processes before exiting itself.
#     """
#     # Iterate through all child processes and send them SIGTERM
#     for child_pid in child_pids:
#         try:
#             os.kill(child_pid, signal.SIGTERM)
#         except OSError as e:
#             print(f"Error killing child process {child_pid}: {e}")
#     # Wait a bit for children to terminate gracefully
#     time.sleep(0.5)

# TODO: ajouter le max de TU
# TODO: rendre le code testable, avec activation/déactivation des SB
# @runtime_checkable  # TODO: what is it ?
class sandboxes:
    """
    Context manager to start and stop the sandbox daemon.
    The parameter `init_fn` is a function that will be called when the daemon starts,
    inside the daemon process. It's a good place to initialize the database connection,
    or to load some data.
    """

    def __init__(self,
                 init_fn: Optional[SyncOrAsyncFunc] = None,
                 config_path: Optional[Union[Path, str]] = None,
                 ) -> None:
        self.init_fn = init_fn  # TODO: invoquer la fn lors du start du process
        self.config_path = config_path
        # TODO: ajouter des paramètres complémentaire ici ?
        # Pas certain, car cela risque de ne pas utiliser le fichier qui est util par ailleur

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> None:
        """
        Start the sandbox daemon.
        """
        from .py_sandbox import read_and_parse_config
        from .remote.os_sandboxes import start_daemon

        logger.debug("__enter__ start...")
        _check_mixte_async_async()
        log_level = logging.root.getEffectiveLevel()
        config = get_config_path(self.config_path).read_text().splitlines()
        config, _, os_sandbox, *_ = read_and_parse_config(config=config)
        start_daemon(os_sandbox, log_level, config)

        def signal_handler(signum: int, frame: object) -> None:
            """
            Handles termination signals (SIGINT, SIGTERM) for the parent process.
            It will kill daemon processes before exiting itself.
            """
            # Iterate through all child processes and send them SIGTERM
            global _current_daemon
            _current_daemon.shutdown()

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
        from .remote.os_sandboxes import shutdown_daemon
        logger.debug("__exit__ start...")
        # If "Cannot call the synchronize sandbox function from another sandbox async function"
        if not isinstance(exc, RuntimeError):
            shutdown_daemon()

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
        from .remote.os_sandboxes import async_start_daemon
        log_level = logging.root.getEffectiveLevel()
        config = get_config_path(self.config_path).read_text().splitlines()
        config, _, os_sandbox, *_ = read_and_parse_config(config=config)
        return await async_start_daemon(os_sandbox, log_level, config)

    async def __aexit__(self,
                        exc_type: Optional[type[BaseException]],
                        exc: Optional[BaseException],
                        tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        from .remote.os_sandboxes import async_shutdown_daemon
        await async_shutdown_daemon()
        return False


def run(main: Coroutine[Any, Any, Any],
        *, debug=None, loop_factory=None,
        init_fn: Optional[SyncOrAsyncFunc] = None,
        config_path: Optional[Union[Path, str]]) -> Any:
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
