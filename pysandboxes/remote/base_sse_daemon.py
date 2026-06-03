# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import json
import logging
import socket
import sys
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Dict

import aiohttp
from aiohttp import ClientConnectorError, ClientPayloadError
from aiohttp_sse_client import client as sse_client

from ..all_rules import AllRules
from ..base_daemon import BaseDaemon
from ..private_loop import get_sandbox_loop, sandbox_loop
from ..sb_types import Envs
from ..tools import get_callable_info, is_in_sandbox
from .parameters import INTERVAL_FOR_RETRY_CONNECTION, TIMEOUT_FOR_RPC_CALL
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
    __slots__ = ("port", "host", "max_connect_retry")

    def __init__(
        self,
        token: str,
        *,
        max_connect_retry: int,
        **kwargs: Dict[str, Any],
    ) -> None:
        super().__init__(token)
        self.port = 0
        # IP literal, not "localhost": aiohttp resolves with
        # AI_ADDRCONFIG, which fails an IPv4 lookup when only 'lo'
        # carries an address (netns, --network none). QEMU hostfwd
        # also needs IPv4, being TCP on 0.0.0.0 only.
        self.host = "127.0.0.1"
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
                from pysandboxes._os_sandbox import get_token

                token = get_token()
                params = _get_rpc_params(args, func, kwargs)

                sandbox_server_url = self.base_url.replace("{PORT}", str(self.port)) + "/rpc"
                logger.info("Calling sandbox at %s", sandbox_server_url)
                logger.debug("Try to call %s", sandbox_server_url)
                # Force IPv4 for localhost/127.0.0.1 so QEMU hostfwd is used.
                session = None
                if self.host in ("127.0.0.1", "localhost"):
                    connector = aiohttp.TCPConnector(family=socket.AF_INET)
                    session = aiohttp.ClientSession(connector=connector)
                event_source_kw: dict[str, Any] = {
                    "option": {"method": "POST"},
                    "json": params,
                    "headers": {
                        "Accept": "text/event-stream",
                        "Authorization": f"Bearer {token}",
                    },
                    "reconnection_time": timedelta(seconds=INTERVAL_FOR_RETRY_CONNECTION),
                    "max_connect_retry": self.max_connect_retry,
                }
                if session is not None:
                    event_source_kw["session"] = session
                async with sse_client.EventSource(
                    sandbox_server_url,
                    **event_source_kw,
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
            raise RuntimeError("The sandbox daemon is being stopped.")

        # Use sandbox loop so the coroutine runs on the loop that is actually
        # running (e.g. in a background thread), avoiding deadlock when the
        # daemon was started from another loop (e.g. pytest async fixture).
        loop = get_sandbox_loop()

        future = asyncio.run_coroutine_threadsafe(
            self.async_call_in_sandbox(func, _force_incomming, *args, **kwargs), loop
        )
        try:
            return future.result(timeout=TIMEOUT_FOR_RPC_CALL)
        except FutureTimeoutError:
            raise RuntimeError(
                f"Sandbox RPC did not respond within {TIMEOUT_FOR_RPC_CALL}s. "
                "Check that the guest is reachable (e.g. QEMU hostfwd, firewall)."
            ) from None

    def update_rules_and_activate(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
        temp: Path,
    ) -> AllRules:
        return all_rules
