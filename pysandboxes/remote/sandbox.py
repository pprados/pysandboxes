import functools
import inspect
import json
import logging
import sys
from typing import Any
from typing import Callable, Optional, Tuple

import httpx

from pysandboxes.remote.tools import _to_b85, _from_b85, is_in_sandbox
from .daemon import HOST, PORT, PATH_RPC

logger = logging.getLogger(__name__)

# URL de votre serveur SSE
SSE_SERVER_URL: str = f"http://{HOST}:{PORT}{PATH_RPC}"

token = "abc123"  # FIXME: a gerer via un context dans l'appelant ?


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


def _sync_rpc(func: Callable[..., Any],
              timeout: float,
              *args: Any,
              **kwargs: Any) -> Any:
    global token
    # Use async context manager for httpx client
    with httpx.Client() as client:
        # Stream the response from the SSE endpoint
        module_name, callable_name = get_callable_info(func)
        params = {
            "token": token,
            "session_id": "123",  # TODO
            "timeout": timeout,
            "function": f"{module_name}:{callable_name}",
            "args": _to_b85(args),
            "kwargs": _to_b85(kwargs),
        }
        with client.stream(
                "POST", SSE_SERVER_URL,
                headers={"Accept": "text/event-stream"},
                json=params,
                follow_redirects=False,
                timeout=None) as response:
            response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)

            # Iterate over chunks of the response body
            for chunk in response.iter_bytes():
                chunk_str: str = chunk.decode("utf-8")
                msg = json.loads(chunk_str)
                if "result" in msg:
                    return _from_b85(msg["result"])
                if "exception" in msg:
                    _reraise(2, *_from_b85(msg["exception"]))
                if "stdout" in msg:
                    print(msg["stdout"], end="")
                if "stderr" in msg:
                    print(msg["stderr"], end="", file=sys.stderr)


async def _async_rpc(func: Callable[..., Any],
                     timeout: float,
                     *args: Any,
                     **kwargs: Any) -> Any:
    global token
    # Use async context manager for httpx client
    async with httpx.AsyncClient() as client:
        # Stream the response from the SSE endpoint
        module_name, callable_name = get_callable_info(func)
        params = {
            "token": token,
            "session_id": "123",  # TODO
            "timeout": timeout,  # TODO
            "function": f"{module_name}:{callable_name}",
            "args": _to_b85(args),
            "kwargs": _to_b85(kwargs),
        }
        async with client.stream(
                "POST", SSE_SERVER_URL,
                headers={"Accept": "text/event-stream"},
                json=params,
                timeout=None) as response:
            response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)

            # Iterate over chunks of the response body
            async for chunk in response.aiter_bytes():
                chunk_str: str = chunk.decode("utf-8")
                msg = json.loads(chunk_str)
                if "result" in msg:
                    return _from_b85(msg["result"])
                if "exception" in msg:
                    _reraise(1, *_from_b85(msg["exception"]))
                if "stdout" in msg:
                    print(msg["stdout"], end="")
                if "stderr" in msg:
                    print(msg["stderr"], end="", file=sys.stderr)


def sandbox(timeout: float = 0) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_in_sandbox():
                # Call original function with captured parameters
                return await _async_rpc(func, timeout, *args, **kwargs)
            else:
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_in_sandbox():
                # Call original function with captured parameters
                return _sync_rpc(func, timeout, *args, **kwargs)
            else:
                return func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
