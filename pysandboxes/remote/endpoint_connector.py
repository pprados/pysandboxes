# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""aiohttp connector that reaches the sandbox over any :class:`Endpoint`."""

import asyncio
import socket
from typing import Any

import aiohttp
from aiohttp import ClientConnectorError, ClientTimeout
from aiohttp.client_proto import ResponseHandler
from aiohttp.client_reqrep import ClientRequest

from .endpoint import TCP, Endpoint, client_socket

# The URL host is ignored by this connector; a fixed name keeps the Host header valid.
ENDPOINT_URL = "http://sandbox"


class EndpointConnector(aiohttp.BaseConnector):
    """Connect to a Unix or VSOCK endpoint, as ``UnixConnector`` does for a Unix path only.

    A refused or missing endpoint surfaces as ``ClientConnectorError``, which the caller's retry loop treats as
    "the daemon is not up yet".
    """

    def __init__(self, endpoint: Endpoint, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._endpoint = endpoint

    async def _create_connection(
        self, req: ClientRequest, traces: list[Any], timeout: ClientTimeout
    ) -> ResponseHandler:
        sock, address = client_socket(self._endpoint)
        try:
            await asyncio.wait_for(self._loop.sock_connect(sock, address), timeout.sock_connect)
            _, proto = await self._loop.create_connection(self._factory, sock=sock)
        except OSError as exc:
            sock.close()
            raise ClientConnectorError(req.connection_key, exc) from exc
        except BaseException:
            sock.close()
            raise
        return proto


def make_session(endpoint: Endpoint, **kwargs: Any) -> aiohttp.ClientSession:
    """Return a session whose requests go to the endpoint, whatever its kind."""
    if endpoint.kind == TCP:
        connector: aiohttp.BaseConnector = aiohttp.TCPConnector(family=socket.AF_INET)
    else:
        connector = EndpointConnector(endpoint)
    return aiohttp.ClientSession(connector=connector, **kwargs)
