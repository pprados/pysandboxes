#!/usr/bin/env python3
import asyncio
import inspect
import json
import logging
import os
import sys
from datetime import timedelta
from typing import Any, Dict, Callable, Optional, Tuple

from aiohttp import ClientPayloadError, ClientConnectorError
from aiohttp_sse_client import client as sse_client
from tblib import pickling_support

from .parameters import HOST, PORT, PATH_RPC
from .tools import from_b85
from ..tools import is_in_sandbox, get_callable_info
from ..base_daemon import BaseDaemon
from ..private_loop import sandbox_loop

pickling_support.install()

logger = logging.getLogger(__name__)

# URL de votre serveur SSE
SANDBOX_SERVER_URL: str = os.environ.get(
    "SANDBOX_SERVER_URL",
    f"http://{"[" + HOST + "]" if "::" in HOST else HOST}:{PORT}{PATH_RPC}")


def _get_rpc_params(args: Any,
                    func: Callable[..., Any],
                    kwargs: Any,
                    timeout: float) -> Dict[str, Any]:
    """
    Get the parameters for the RPC call.
    """
    from .tools import to_b85
    module_name, callable_name = get_callable_info(func)
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
    def __init__(self, token: str):
        super().__init__(token)

    async def async_call_in_sandbox(self,
                                    func: Callable[..., Any],
                                    timeout: float,
                                    *args: Any,
                                    **kwargs: Any) -> Any:
        if is_in_sandbox():
            return await func(*args, **kwargs)
        from pysandboxes.os_sandbox import get_token

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
                    reconnection_time=
                    timedelta(
                        # seconds=30 # FIXME
                        seconds=0.2
                        ),
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
        except ClientPayloadError:
            raise RuntimeError("No result received from the sandbox")
        except ClientConnectorError:
            while True:  # FIXME: Pour attendre le debug
                await asyncio.sleep(10)
            raise RuntimeError("Impossible to connect to the sandbox")
        except SystemExit:
            raise
        except Exception as e:
            raise RuntimeError(e)  # FIXME: qu'en faire ?

    @sandbox_loop
    def call_in_sandbox(self,
                        func: Callable[..., Any],
                        timeout: float,
                        *args: Any,
                        **kwargs: Any) -> Any:
        if is_in_sandbox():
            return func(*args, **kwargs)
        loop = asyncio.get_event_loop()  # Get the current running loop. May be != sandbox loop

        return asyncio.run_coroutine_threadsafe(
            self.async_call_in_sandbox(func, timeout, *args, **kwargs),
            loop).result()
