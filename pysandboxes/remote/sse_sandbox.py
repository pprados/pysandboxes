#!/usr/bin/env python3
import asyncio
import base64
import json
import logging
import os
import pickle
import sys
from datetime import timedelta
from typing import Any, Dict, Callable

from aiohttp import ClientPayloadError, ClientConnectorError
from aiohttp_sse_client import client as sse_client

from .parameters import HOST, PORT, PATH_RPC
from .tools import to_b85, from_b85
from ..base_daemon import BaseDaemon
from ..private_loop import sandbox_loop
from ..tools import is_in_sandbox, get_callable_info

logger = logging.getLogger(__name__)

# URL de votre serveur SSE
SANDBOX_SERVER_URL: str = os.environ.get(
    "SANDBOX_SERVER_URL",
    f"http://{"[" + HOST + "]" if "::" in HOST else HOST}:{PORT}{PATH_RPC}")

PING_SERVER_URL: str = os.environ.get(
    "SANDBOX_SERVER_URL",
    f"http://{"[" + HOST + "]" if "::" in HOST else HOST}:{PORT}/ping")


def _get_rpc_params(args: Any,
                    func: Callable[..., Any],
                    kwargs: Any,
                    timeout: float) -> Dict[str, Any]:
    """
    Get the parameters for the RPC call.
    """

    module_name, callable_name = get_callable_info(func)
    params = {
        "session_id": "123",  # FIXME: session_id (correlation id?)
        "timeout": timeout,
        "function": f"{module_name}:{callable_name}",
        "args": to_b85(args),
        "kwargs": to_b85(kwargs),
    }
    return params


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
        import pickle

        try:
            token = get_token()
            params = _get_rpc_params(args, func, kwargs, timeout)
            logger.debug("Try to call to %s", SANDBOX_SERVER_URL)
            async with sse_client.EventSource(
                    SANDBOX_SERVER_URL,
                    # session=session,  # TODO: Use a correlationid?
                    option={"method": "POST"},
                    json=params,
                    headers={
                        "Accept": "text/event-stream",
                        "Authorization": f"Bearer {token}"
                    },
                    timeout=None,  # keep-alive
                    reconnection_time=
                    timedelta(
                        seconds=0.2
                    ),
            ) as event_source:
                async for event in event_source:
                    msg = json.loads(event.data)
                    if "result" in msg:
                        return from_b85(msg["result"])
                    if "exception" in msg:
                        exception, serial_traceback = from_b85(msg["exception"])
                        traceback = serial_traceback.as_traceback()
                        remove = 3
                        while remove:
                            remove -= 1
                            if traceback.tb_next:
                                traceback = traceback.tb_next
                            else:
                                break
                        raise exception.with_traceback(traceback)

                    if "stdout" in msg:
                        print(msg["stdout"], end="")
                    if "stderr" in msg:
                        print(msg["stderr"], end="", file=sys.stderr)
                raise RuntimeError("No result received from the sandbox")
        except ClientPayloadError:
            raise RuntimeError("No result received from the sandbox")
        except ClientConnectorError:
            raise RuntimeError("Impossible to connect to the sandbox")
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

        return asyncio.run_coroutine_threadsafe(
            self.async_call_in_sandbox(func, timeout, *args, **kwargs),
            loop).result()
