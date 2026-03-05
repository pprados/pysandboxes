# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import json
import logging
import sys
from datetime import timedelta
from typing import Any, Callable, Dict

from aiohttp import ClientConnectorError, ClientPayloadError
from aiohttp_sse_client import client as sse_client

from ..base_daemon import BaseDaemon
from ..private_loop import sandbox_loop
from ..tools import get_callable_info, is_in_sandbox
from .parameters import INTERVAL_FOR_RETRY_CONNECTION
from .tools import from_b85, to_b85

logger = logging.getLogger(__name__)


def _get_rpc_params(
    args: Any,
    func: Callable[..., Any],
    kwargs: Any,
) -> Dict[str, Any]:
    """
    Get the parameters for the RPC call.
    """

    module_name, callable_name = get_callable_info(func)
    params = {
        "session_id": "123",  # TODO: session_id with correlation id?
        "function": f"{module_name}:{callable_name}",
        "args": to_b85(args),
        "kwargs": to_b85(kwargs),
    }
    return params


class BaseSSESandbox(BaseDaemon):
    __slots__ = ("port", "host","max_connect_retry")

    def __init__(
        self,
        token: str,
        *,
        max_connect_retry: int,
        **kwargs: Dict[str, Any],
    ) -> None:
        super().__init__(token)
        self.port = 0
        self.host = "localhost"
        self.max_connect_retry = max_connect_retry

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{{PORT}}"

    async def async_call_in_sandbox(
        self,
        func: Callable[..., Any],
        _force_incomming: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if is_in_sandbox():
            return await func(*args, **kwargs)
        if not _force_incomming and not self._accept_incoming:
            raise RuntimeError("The sandbox daemon is being stopped.")

        retry = self.max_connect_retry
        while retry > 0:
            try:
                from pysandboxes.os_sandbox import get_token

                token = get_token()
                params = _get_rpc_params(args, func, kwargs)

                sandbox_server_url = (
                    self.base_url.replace("{PORT}", str(self.port)) + "/rpc"
                )
                logger.debug("Try to call %s", sandbox_server_url)
                async with sse_client.EventSource(
                    sandbox_server_url,
                    # session=session,  # TODO: Use a correlationid?
                    option={"method": "POST"},
                    json=params,
                    headers={
                        "Accept": "text/event-stream",
                        "Authorization": f"Bearer {token}",
                    },
                    reconnection_time=timedelta(seconds=INTERVAL_FOR_RETRY_CONNECTION),
                    max_connect_retry=self.max_connect_retry,
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
            except (ClientPayloadError, ClientConnectorError, ConnectionRefusedError):
                logger.debug("Connection error. Retry")
                retry -= 1
                continue
            except ClientConnectorError:
                raise RuntimeError("Impossible to connect to the sandbox")
            except SystemExit:
                raise
            # Other exceptions are from the called function

        raise RuntimeError("No result received from the sandbox")

    @sandbox_loop
    def call_in_sandbox(
        self,
        func: Callable[..., Any],
        _force_incomming: bool,
        *args: Any,
        **kwargs: Dict[str, Any],
    ) -> Any:
        if is_in_sandbox():
            return func(*args, **kwargs)
        if not _force_incomming and not self._accept_incoming:
            raise RuntimeError("The sandbox demon is being stopped.")

        loop = (
            asyncio.get_event_loop()
        )  # Get the current running loop. May be != sandbox loop

        return asyncio.run_coroutine_threadsafe(
            self.async_call_in_sandbox(func, _force_incomming, *args, **kwargs), loop
        ).result()
