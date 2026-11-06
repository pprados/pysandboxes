# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The filtering resolver of one sandbox, run on its own thread, for ``net-resolve=runtime``.

The provider starts it before it builds the firewall, because the redirection of the sandbox DNS needs the port, and
attaches the enforcer once the network namespace exists. Until then every answer is withheld: no address is ever
returned that has not been opened. The names the rules allow are forwarded to the resolvers of the host over TCP, so
that a long answer arrives whole.
"""

import asyncio
import logging
import socket
import struct
import threading
from ipaddress import IPv4Address
from typing import Sequence

from ..egress_filter import Enforcer, FilteringResolver, IPAddress, NameRule

logger = logging.getLogger(__name__)

UPSTREAM_PORT = 53
UPSTREAM_TIMEOUT = 2.0


class _DeferredEnforcer:
    """The enforcer of a resolver that is already listening; it refuses until a real one is attached."""

    def __init__(self) -> None:
        self._enforcer: Enforcer | None = None

    def attach(self, enforcer: Enforcer) -> None:
        self._enforcer = enforcer

    def allow(self, ip: IPAddress, rule: NameRule, ttl: int) -> None:
        if self._enforcer is None:
            raise OSError("the sandbox network is not ready: nothing can be opened yet")
        self._enforcer.allow(ip, rule, ttl)

    def revoke(self, ip: IPAddress, rule: NameRule) -> None:
        if self._enforcer is not None:
            self._enforcer.revoke(ip, rule)


def _forward_tcp(servers: Sequence[IPv4Address], port: int, timeout: float, packet: bytes) -> bytes:
    """Ask the first resolver of ``servers`` that answers; raise ``OSError`` when none does."""
    last: Exception = OSError("no resolver of the host is known")
    for server in servers:
        try:
            with socket.create_connection((str(server), port), timeout=timeout) as conn:
                conn.sendall(struct.pack(">H", len(packet)) + packet)
                header = _read(conn, 2)
                return _read(conn, struct.unpack(">H", header)[0])
        except OSError as error:
            last = error
    raise OSError(f"no resolver of the host answered: {last}")


def _read(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise OSError("the resolver closed the connection")
        data += chunk
    return data


class RuntimeDns:
    """A ``FilteringResolver`` on a thread of its own. One instance serves one sandbox."""

    def __init__(
        self,
        rules: tuple[NameRule, ...],
        upstream_servers: Sequence[IPv4Address],
        *,
        upstream_port: int = UPSTREAM_PORT,
        upstream_timeout: float = UPSTREAM_TIMEOUT,
    ) -> None:
        self._deferred = _DeferredEnforcer()
        self._resolver = FilteringResolver(
            rules,
            self._deferred,
            lambda packet: _forward_tcp(upstream_servers, upstream_port, upstream_timeout, packet),
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._port = 0
        self._failure: BaseException | None = None

    def attach(self, enforcer: Enforcer) -> None:
        self._deferred.attach(enforcer)

    def start(self) -> int:
        """Listen on an ephemeral loopback port, on a thread of its own, and return the port."""
        self._thread = threading.Thread(target=self._run, name="runtime-dns", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._failure is not None:
            raise OSError(f"the filtering resolver cannot start: {self._failure}") from self._failure
        return self._port

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            self._port = loop.run_until_complete(self._resolver.start())
        except BaseException as error:
            self._failure = error
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
            loop.run_until_complete(self._resolver.stop())
        finally:
            loop.close()

    def stop(self) -> None:
        """Close the sockets and end the thread; harmless when already stopped."""
        thread, loop = self._thread, self._loop
        self._thread = None
        if thread is None or loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
