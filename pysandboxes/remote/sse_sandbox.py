#!/usr/bin/env python3
import asyncio
import inspect
import json
import logging
import os
import sys
import traceback
from datetime import timedelta
from typing import Any, Dict, Callable, Optional, Tuple

from tblib import pickling_support

from .base_daemon import BaseDaemon, _mixed_sync_and_async_error
from .manage_loop import sandbox_loop, get_sandbox_loop
from .parameters import HOST, PORT, PATH_RPC
from .tools import is_in_sandbox

pickling_support.install()

logger = logging.getLogger(__name__)

# URL de votre serveur SSE
SANDBOX_SERVER_URL: str = os.environ.get(
    "SANDBOX_SERVER_URL",
    f"http://{"[" + HOST + "]" if "::" in HOST else HOST}:{PORT}{PATH_RPC}")

def _get_callable_info(func: Callable[..., Any]) -> Tuple[Optional[str], Optional[str]]:
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


def _get_rpc_params(args: Any,
                    func: Callable[..., Any],
                    kwargs: Any,
                    timeout: float) -> Dict[str, Any]:
    """
    Get the parameters for the RPC call.
    """
    from .tools import to_b85
    module_name, callable_name = _get_callable_info(func)
    params = {
        "session_id": "123",  # TODO
        "timeout": timeout,  # TODO
        "function": f"{module_name}:{callable_name}",
        "args": to_b85(args),
        "kwargs": to_b85(kwargs),
    }
    return params


def _reraise(remove: int, tp, value, tb=None):
    while remove:
        remove -= 1
        if tb.tb_next:
            tb = tb.tb_next
    raise value.with_traceback(tb)


class SSESandbox(BaseDaemon):
    def __init__(self, token: Optional[str] = None):
        super().__init__(token)

    async def async_call_in_sandbox(self,
                                    func: Callable[..., Any],
                                    timeout: float,
                                    *args: Any,
                                    **kwargs: Any) -> Any:
        if is_in_sandbox():
            return await func(*args, **kwargs)
        from .tools import from_b85
        from .os_sandboxes import get_token
        from aiohttp_sse_client import client as sse_client

        try:
            token = get_token()
            params = _get_rpc_params(args, func, kwargs, timeout)
            logger.debug("Try to call to %s", SANDBOX_SERVER_URL)
            async with sse_client.EventSource(
                    SANDBOX_SERVER_URL,
                    # session=session,  # TODO: garder la session ouverte pour reutiliser ?
                    option={"method": "POST"},
                    json=params,
                    headers={
                        "Accept": "text/event-stream",
                        "Authorization": f"Bearer {token}"
                    },
                    timeout=None,  # keep-alive
                    reconnection_time=timedelta(seconds=0.2),
            ) as event_source:
                async for event in event_source:
                    msg = json.loads(event.data)
                    if "result" in msg:
                        return from_b85(msg["result"])
                    if "exception" in msg:
                        _reraise(1,
                                 *from_b85(msg["exception"]))  # FIXME: check remove: 1
                    if "stdout" in msg:
                        print(msg["stdout"], end="")
                    if "stderr" in msg:
                        print(msg["stderr"], end="", file=sys.stderr)
                raise RuntimeError("No result received from the sandbox")
        except SystemExit:
            raise

    @sandbox_loop
    def call_in_sandbox(self,
                        func: Callable[..., Any],
                        timeout: float,
                        *args: Any,
                        **kwargs: Any) -> Any:
        if is_in_sandbox():
            return func(*args, **kwargs)
        loop = asyncio.get_event_loop()  # Get the current running loop. May be != sandbox loop
        # if loop == get_sandbox_loop():  # FIXME: si je détecter, ca fait planter des trucs
        #     raise RuntimeError(_mixed_sync_and_async_error)

        return asyncio.run_coroutine_threadsafe(
            self.async_call_in_sandbox(func, timeout, *args, **kwargs),
            loop).result()
