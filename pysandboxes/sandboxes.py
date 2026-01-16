import asyncio
import functools
import inspect
import logging
from multiprocessing import Lock
from pathlib import Path
from typing import Any, TypeVar, Union, \
    Awaitable, Coroutine
from typing import Callable, Optional

from .py_sandbox import get_config_path, read_and_parse_config
from .remote.base_daemon import BaseDaemon, _mixed_sync_and_async_error
from .remote.manage_loop import set_sandbox_loop
from .remote.os_sandboxes import shutdown_daemon, _async_start_daemon, is_daemon_started

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
        log_level = logging.root.getEffectiveLevel()
        config = get_config_path(self.config_path).read_text().splitlines()
        config, _, os_sandbox, *_ = read_and_parse_config(config=config)
        start_daemon(os_sandbox, log_level, config)
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
        config_path: Optional[Union[Path, str]]) -> Any:
    """
    Run the main coroutine in a new event loop, with the sandbox
    It's similar to `asyncio.run()`, but with the sandbox.
    The parameters are the same as `asyncio.run()`.
    """

    async def _run():
        # In this context, use the standard running loop.
        # the sandbox will be started before the main coroutine.
        loop = asyncio.get_running_loop()
        set_sandbox_loop(loop)
        # Config the sandbox
        log_level = logging.root.getEffectiveLevel()
        config = get_config_path(config_path).read_text().splitlines()
        config, _, os_sandbox, *_ = read_and_parse_config(config=config)
        await loop.create_task(_async_start_daemon(os_sandbox, log_level, config),
                               name="_async_start_daemon")
        result = (await asyncio.create_task(main), "start sandbox in run")
        # All remaining tasks are canceled by the Runner
        return result

    try:
        result = asyncio.run(_run())
        return result
    except RuntimeError as e:
        if str(e) == _mixed_sync_and_async_error:
            raise
        else:
            if is_daemon_started():
                shutdown_daemon()
    except BaseException:
        if is_daemon_started():
            shutdown_daemon()
