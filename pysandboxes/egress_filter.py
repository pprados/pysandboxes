# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Runtime egress filter: judge a host name when it is resolved, not when the sandbox starts.

``guard_socket`` freezes the addresses of the names of the ``net=`` rules at start (``pin_dns``). This module is the
other model: a name is judged by a ``NameRule`` list when a sandboxed program asks for it, the addresses of an
allowed answer are learned for the length of their TTL, and an ``Enforcer`` makes them reachable in the sandbox
network. The module knows no provider: the enforcer is the provider's part.
"""

import asyncio
import logging
import struct
import time
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Callable, Coroutine, Hashable, NamedTuple, Protocol, cast

logger = logging.getLogger(__name__)

IPAddress = IPv4Address | IPv6Address

MIN_LEARNED_TTL = 60
MAX_LEARNED_TTL = 3600

# ``net-resolve=``: ``pinned`` freezes the addresses of the names of the ``net=`` rules at start (``pin_dns``);
# ``runtime`` resolves them when the sandboxed program asks. The value used when the key is absent is this one line.
NET_RESOLVE_MODES = ("pinned", "runtime")
DEFAULT_NET_RESOLVE = "pinned"


def _normalize(name: str) -> str:
    return name.strip().rstrip(".").lower()


class NameRule(NamedTuple):
    """One host name rule: ``example.com`` (name and subdomains), ``=example.com`` (name only), ``*.example.com``.

    ``kinds`` are the protocols (``tcp``, ``udp``) and ``ports`` the inclusive ``(low, high)`` ranges the rule opens
    on the addresses of the name; no range means every port. A DENY rule refuses the name whatever the port.
    """

    allow: bool
    pattern: str
    kinds: tuple[str, ...] = ("tcp", "udp")
    ports: tuple[tuple[int, int], ...] = ()

    def matches(self, name: str) -> bool:
        host = _normalize(name)
        if not host:
            return False
        pattern = _normalize(self.pattern)
        if pattern.startswith("="):
            return host == pattern[1:]
        if pattern.startswith("*."):
            return host.endswith(pattern[1:])
        return host == pattern or host.endswith("." + pattern)


def allowing_rules(rules: tuple[NameRule, ...], name: str) -> list[NameRule]:
    """The ALLOW rules that open ``name``: those matching it, in order, up to the first matching DENY.

    Empty when no rule allows the name (default deny): the name is then refused.
    """
    found: list[NameRule] = []
    for rule in rules:
        if rule.matches(name):
            if not rule.allow:
                break
            found.append(rule)
    return found


def clamp_ttl(ttl: int) -> int:
    return max(MIN_LEARNED_TTL, min(MAX_LEARNED_TTL, ttl))


class LearnedTable:
    """Keys learned from allowed answers (an address, or an ``(address, rule)`` pair), each with an expiry.

    The clock is injectable so that a test moves time without sleeping.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._expiry: dict[Hashable, float] = {}

    def learn(self, keys: list[Any], ttl: int) -> list[Any]:
        """Record ``keys`` for the clamped ``ttl``; return those that were not already allowed (to be opened)."""
        deadline = self._clock() + clamp_ttl(ttl)
        new = [key for key in keys if not self.allows(key)]
        for key in keys:
            self._expiry[key] = max(deadline, self._expiry.get(key, 0.0))
        return new

    def allows(self, key: Hashable) -> bool:
        deadline = self._expiry.get(key)
        return deadline is not None and self._clock() < deadline

    def expired(self) -> list[Any]:
        """Remove and return the keys whose deadline has passed."""
        now = self._clock()
        gone = [key for key, deadline in self._expiry.items() if now >= deadline]
        for key in gone:
            del self._expiry[key]
        return gone


class Enforcer(Protocol):
    """What makes an address reachable, or not, in the sandbox network. Provided by the provider."""

    def allow(self, ip: IPAddress, rule: NameRule, ttl: int) -> None: ...

    def revoke(self, ip: IPAddress, rule: NameRule) -> None: ...


_HEADER = 12
_UDP_LIMIT = 512
_FLAGS_RESPONSE = 0x8180


def _skip_name(packet: bytes, offset: int) -> int:
    while True:
        length = packet[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length


def _question_end(packet: bytes) -> int | None:
    try:
        if len(packet) < _HEADER or struct.unpack(">H", packet[4:6])[0] < 1:
            return None
        end = _skip_name(packet, _HEADER) + 4
    except IndexError:
        return None
    return end if end <= len(packet) else None


def question_name(packet: bytes) -> str | None:
    """The name of the first question, lower case and dotted; ``None`` for a packet that is not a query."""
    if _question_end(packet) is None:
        return None
    labels: list[str] = []
    offset = _HEADER
    try:
        while packet[offset]:
            length = packet[offset]
            if length & 0xC0:
                return None
            labels.append(packet[offset + 1 : offset + 1 + length].decode("ascii"))
            offset += 1 + length
    except (IndexError, UnicodeDecodeError):
        return None
    return ".".join(labels).lower() or None


def _reply(packet: bytes, rcode: int) -> bytes:
    end = _question_end(packet)
    head = packet[:2] + struct.pack(">HHHHH", _FLAGS_RESPONSE | rcode, 1, 0, 0, 0)
    return head + packet[_HEADER:end]


def nxdomain(packet: bytes) -> bytes:
    return _reply(packet, 3)


def servfail(packet: bytes) -> bytes:
    return _reply(packet, 2)


def answer_records(packet: bytes) -> list[tuple[IPAddress, int]]:
    """The ``(address, ttl)`` of the A and AAAA records of the answer section; CNAMEs and the rest are skipped."""
    records: list[tuple[IPAddress, int]] = []
    try:
        offset = _question_end(packet)
        if offset is None:
            return []
        for _ in range(struct.unpack(">H", packet[6:8])[0]):
            offset = _skip_name(packet, offset)
            rtype, _cls, ttl, size = struct.unpack(">HHIH", packet[offset : offset + 10])
            rdata = packet[offset + 10 : offset + 10 + size]
            if len(rdata) != size:
                return records
            if rtype == 1 and size == 4:
                records.append((IPv4Address(rdata), ttl))
            elif rtype == 28 and size == 16:
                records.append((IPv6Address(rdata), ttl))
            offset += 10 + size
    except (IndexError, struct.error):
        pass
    return records


def _truncate(reply: bytes) -> bytes:
    flags = struct.unpack(">H", reply[2:4])[0] | 0x0200
    return reply[:2] + struct.pack(">HHHHH", flags, 1, 0, 0, 0) + reply[_HEADER : _question_end(reply)]


class _UdpServer(asyncio.DatagramProtocol):
    def __init__(self, resolver: "FilteringResolver") -> None:
        self._resolver = resolver
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._resolver.spawn(self._handle(data, addr))

    async def _handle(self, data: bytes, addr: tuple[str, int]) -> None:
        reply = await self._resolver.answer(data, udp=True)
        if reply is not None and self._transport is not None:
            self._transport.sendto(reply, addr)


class FilteringResolver:
    """A DNS server on host loopback that answers only the names the rules allow.

    An allowed name is forwarded to ``upstream``; every address of the answer is opened through the ``enforcer``
    before the reply goes back, so the first packet of the program never meets a closed address. Addresses are
    revoked when their TTL, clamped to [60, 3600] s, is over. One instance serves one sandbox.
    """

    def __init__(
        self,
        rules: tuple[NameRule, ...],
        enforcer: Enforcer,
        upstream: Callable[[bytes], bytes],
        table: LearnedTable | None = None,
        reap_interval: float = 1.0,
        host: str = "127.0.0.1",
    ) -> None:
        self._host = host
        self._rules = rules
        self._enforcer = enforcer
        self._upstream = upstream
        self._table = table if table is not None else LearnedTable()
        self._reap_interval = reap_interval
        self._udp: asyncio.DatagramTransport | None = None
        self._tcp: asyncio.Server | None = None
        self._reaper: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start(self) -> int:
        """Bind UDP and TCP on the same ephemeral port of ``host`` (the loopback by default) and return it."""
        loop = asyncio.get_running_loop()
        for _ in range(20):
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: _UdpServer(self), local_addr=(self._host, 0)
            )
            port: int = transport.get_extra_info("sockname")[1]
            try:
                self._tcp = await asyncio.start_server(self._serve_tcp, self._host, port)
            except OSError:
                transport.close()
                continue
            self._udp = cast(asyncio.DatagramTransport, transport)
            self._reaper = loop.create_task(self._reap())
            return port
        raise OSError("no loopback port is free for both UDP and TCP")

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
        for task in list(self._tasks):
            task.cancel()
        if self._udp is not None:
            self._udp.close()
        if self._tcp is not None:
            self._tcp.close()
            await self._tcp.wait_closed()
        await asyncio.sleep(0)

    async def answer(self, packet: bytes, udp: bool) -> bytes | None:
        """The reply to ``packet``, or ``None`` when it is not a query (dropped, never answered)."""
        name = question_name(packet)
        if name is None:
            return None
        rules = allowing_rules(self._rules, name)
        if not rules:
            return nxdomain(packet)
        try:
            reply = await asyncio.to_thread(self._upstream, packet)
            if reply[3] & 0x0F:
                return reply
            for ip, ttl in answer_records(reply):
                for rule in rules:
                    if not self._table.allows((ip, rule)):
                        await asyncio.to_thread(self._enforcer.allow, ip, rule, clamp_ttl(ttl))
                    self._table.learn([(ip, rule)], ttl)
        except Exception:
            logger.warning("egress filter: %s withheld, upstream or enforcer failed", name, exc_info=True)
            return servfail(packet)
        return _truncate(reply) if udp and len(reply) > _UDP_LIMIT else reply

    async def _serve_tcp(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                size = struct.unpack(">H", await reader.readexactly(2))[0]
                reply = await self.answer(await reader.readexactly(size), udp=False)
                if reply is None:
                    break
                writer.write(struct.pack(">H", len(reply)) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            for ip, rule in self._table.expired():
                try:
                    await asyncio.to_thread(self._enforcer.revoke, ip, rule)
                except Exception:
                    logger.warning("egress filter: revoking %s failed", ip, exc_info=True)
