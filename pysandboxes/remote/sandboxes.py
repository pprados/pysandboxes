import asyncio
import functools
import inspect
import json
import logging
import os
import sys
import traceback
from datetime import timedelta
from multiprocessing import Lock
from typing import Any, TypeVar, Union, \
    Awaitable, TYPE_CHECKING
from typing import Callable, Optional, Tuple

from aiohttp_sse_client import client as sse_client

from .base_daemon import BaseDaemon
from .manage_loop import sandbox_loop
from .parameters import HOST, PORT, PATH_RPC
if TYPE_CHECKING:
    from .os_sandbox import async_start_daemon, start_daemon, shutdown_daemon, \
        async_shutdown_daemon
    from .tools import _to_b85, _from_b85, is_in_sandbox

logger = logging.getLogger(__name__)

# URL de votre serveur SSE
SANDBOX_SERVER_URL: str = os.environ.get(
    "SANDBOX_SERVER_URL",
    f"http://{"[" + HOST + "]" if "::" in HOST else HOST}:{PORT}{PATH_RPC}")

token = "abc123"  # FIXME: token a gerer via un context dans l'appelant ?

_lock = Lock()


def _reraise(remove: int, tp, value, tb=None):
    while remove:
        remove -= 1
        if tb.tb_next:
            tb = tb.tb_next
    raise value.with_traceback(tb)


def get_callable_info(func: Callable[..., Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves the module name and the fully qualified name of a callable.

    Args:
        func: The callable object (function, method, class method, static method,
              lambda, or callable instance).

    Returns:
        A tuple containing:
        - The name of the module where the callable is defined (str or None).
        - The fully qualified name of the callable (str or None).
    """
    module_name: Optional[str] = None
    callable_name: Optional[str] = None

    # Get the module name using inspect.getmodule()
    # This works well for functions, methods, and class methods
    module_obj = inspect.getmodule(func)
    if module_obj:
        module_name = module_obj.__name__

    # Get the qualified name of the callable
    # __qualname__ provides the dotted path from the module to the callable,
    # useful for nested functions or methods within classes.
    # __name__ provides just the simple name.
    if hasattr(func, '__qualname__'):
        callable_name = func.__qualname__
    elif hasattr(func, '__name__'):
        callable_name = func.__name__
    elif inspect.ismethod(func):
        # For bound methods, func.__func__ gives the underlying function
        if hasattr(func.__func__, '__qualname__'):
            callable_name = func.__func__.__qualname__
        elif hasattr(func.__func__, '__name__'):
            callable_name = func.__func__.__name__
    elif isinstance(func, type):  # It's a class
        callable_name = func.__qualname__
    elif hasattr(func, '__class__') and hasattr(func.__class__, '__call__'):
        # It's an instance of a class with a __call__ method
        callable_name = func.__class__.__qualname__
        if callable_name:
            callable_name += ".__call__"
    return module_name, callable_name


def _get_rpc_params(args, func, kwargs, timeout, token):
    """
    Get the parameters for the RPC call.
    """
    from .tools import _to_b85
    module_name, callable_name = get_callable_info(func)
    params = {
        "token": token,
        "session_id": "123",  # TODO
        "timeout": timeout,  # TODO
        "function": f"{module_name}:{callable_name}",
        "args": _to_b85(args),
        "kwargs": _to_b85(kwargs),
    }
    return params


async def _async_rpc(func: Callable[..., Any],
                     timeout: float,
                     *args: Any,
                     **kwargs: Any) -> Any:
    from .tools import _from_b85
    global token
    try:
        params = _get_rpc_params(args, func, kwargs, timeout, token)
        async with sse_client.EventSource(  # ← method override here
                SANDBOX_SERVER_URL,
                # session=session,  # TODO: garder la session ouverte pour reutiliser ?
                option={"method": "POST"},
                json=params,
                headers={"Accept": "text/event-stream"},
                timeout=None,  # keep-alive
                reconnection_time=timedelta(seconds=0.5),
        ) as event_source:
            async for event in event_source:
                msg = json.loads(event.data)
                if "result" in msg:
                    return _from_b85(msg["result"])
                if "exception" in msg:
                    _reraise(1, *_from_b85(msg["exception"]))  # FIXME: check remove: 1
                if "stdout" in msg:
                    print(msg["stdout"], end="")
                if "stderr" in msg:
                    print(msg["stderr"], end="", file=sys.stderr)
    except SystemExit:
        raise
    except Exception:
        logger.error(
            f"Client Error when calling the sandbox: {traceback.format_exc()}")  # FIXME
        raise


@sandbox_loop
def _sync_rpc(func: Callable[..., Any],
              timeout: float,
              *args: Any,
              **kwargs: Any) -> Any:
    loop = asyncio.get_event_loop()  # Get the current running loop
    return asyncio.run_coroutine_threadsafe(
        _async_rpc(func, timeout, *args, **kwargs),
        loop).result()


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

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            from .tools import is_in_sandbox
            if not is_in_sandbox():
                # Call original function with captured parameters
                return await _async_rpc(func, timeout, *args, **kwargs)
            else:
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            from .tools import is_in_sandbox
            if not is_in_sandbox():
                # Call original function with captured parameters
                return _sync_rpc(func, timeout, *args, **kwargs)
            else:
                return func(*args, **kwargs)

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
# @runtime_checkable
class sandboxes:
    """
    Context manager to start and stop the sandbox daemon.
    The parameter `init_fn` is a function that will be called when the daemon starts,
    inside the daemon process. It's a good place to initialize the database connection,
    or to load some data.
    """

    def __init__(self,
                 init_fn: Optional[SyncOrAsyncFunc] = None
                 ) -> None:
        self.init_fn = init_fn  # TODO: invoquer la fn lors du start du process
        # TODO: ajouter des paramètres complémentaire ici ?
        # Pas certain, car cela risque de ne pas utiliser le fichier qui est util par ailleur

    # ── synchronous API ────────────────────────────────
    def __enter__(self) -> None:
        """
        Start the sandbox daemon.
        """
        from ..guard_sandbox import read_and_parse_config
        from .os_sandbox import start_daemon

        logger.debug("__enter__ start...")
        log_level = logging.root.getEffectiveLevel()
        _, os_sandbox, *_ = read_and_parse_config()
        start_daemon(os_sandbox, log_level)
        logger.debug("__enter__ ok")

    def __exit__(self,
                 exc_type: Optional[type[BaseException]],
                 exc: Optional[BaseException],
                 tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        from .os_sandbox import shutdown_daemon
        logger.debug("__exit__ start...")
        shutdown_daemon()
        logger.debug("__exit__ done")
        return False

    # ── asynchronous API ───────────────────────────────
    async def __aenter__(self) -> BaseDaemon:
        """
        Start the sandbox daemon.
        """
        from ..guard_sandbox import read_and_parse_config
        log_level = logging.root.getEffectiveLevel()
        _, os_sandbox, *_ = read_and_parse_config()
        await async_start_daemon(os_sandbox, log_level)

    async def __aexit__(self,
                        exc_type: Optional[type[BaseException]],
                        exc: Optional[BaseException],
                        tb: Optional[Any]) -> bool:
        """
        Stop the sandbox daemon.
        """
        await async_shutdown_daemon()
        return False


def run(main, *, debug=None, loop_factory=None, cancel_remaining_tasks=True) -> Any:
    """
    Run the main coroutine in a new event loop, with the sandbox
    It's similar to `asyncio.run()`, but with the sandbox.
    The parameters are the same as `asyncio.run()`.
    cancem_remaining_tasks: if True, cancel all remaining tasks when the main coroutine is done.
    """

    async def _run():
        async with sandboxes():
            result = (await asyncio.gather(main))[0]

        # Cancel all remaining tasks
        if cancel_remaining_tasks:
            loop = asyncio.get_running_loop()
            tasks_to_cancel = [
                task for task in asyncio.all_tasks(loop) if
                task is not asyncio.current_task()
            ]

            if tasks_to_cancel:
                # Cancelling all task
                for task in tasks_to_cancel:
                    task.cancel()

                # Wait for all cancelled tasks to complete their cleanup
                done, _ = await asyncio.wait(tasks_to_cancel)
            return result

    return asyncio.run(_run())
    # return asyncio.run(_run(), debug=debug, loop_factory=loop_factory) # FIXME
