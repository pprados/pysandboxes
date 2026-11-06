# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import asyncio
import socket
import struct
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Awaitable, Callable

import pytest

from pysandboxes.egress_filter import (
    FilteringResolver,
    LearnedTable,
    NameRule,
    answer_records,
    nxdomain,
    question_name,
    servfail,
)

RULES = (NameRule(False, "bad.example.com"), NameRule(True, "example.com"))


def _name(name: str) -> bytes:
    return b"".join(bytes([len(label)]) + label.encode() for label in name.split(".")) + b"\x00"


def query(name: str, qtype: int = 1, ident: int = 0x1234) -> bytes:
    return struct.pack(">HHHHHH", ident, 0x0100, 1, 0, 0, 0) + _name(name) + struct.pack(">HH", qtype, 1)


def response(q: bytes, answers: list[tuple[int, int, bytes]], rcode: int = 0) -> bytes:
    """A response to ``q``: ``answers`` are ``(type, ttl, rdata)``, named with a pointer to the question."""
    head = q[:2] + struct.pack(">HHHHH", 0x8180 | rcode, 1, len(answers), 0, 0)
    body = b"".join(b"\xc0\x0c" + struct.pack(">HHIH", t, 1, ttl, len(rd)) + rd for t, ttl, rd in answers)
    return head + q[12:] + body


def a_record(ip: str, ttl: int = 300) -> tuple[int, int, bytes]:
    return 1, ttl, IPv4Address(ip).packed


class FakeEnforcer:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.rules: list[NameRule] = []
        self.fail = False

    def allow(self, ip: IPv4Address | IPv6Address, rule: NameRule, ttl: int) -> None:
        if self.fail:
            raise OSError("iptables failed")
        self.events.append(("allow", str(ip)))
        self.rules.append(rule)

    def revoke(self, ip: IPv4Address | IPv6Address, rule: NameRule) -> None:
        self.events.append(("revoke", str(ip)))


class Upstream:
    def __init__(self, answers: list[tuple[int, int, bytes]], rcode: int = 0) -> None:
        self.answers, self.rcode, self.calls = answers, rcode, 0

    def __call__(self, packet: bytes) -> bytes:
        self.calls += 1
        return response(packet, self.answers, self.rcode)


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def run(scenario: Callable[[FilteringResolver, int], Awaitable[None]], resolver: FilteringResolver) -> None:
    async def main() -> None:
        port = await resolver.start()
        try:
            await scenario(resolver, port)
        finally:
            await resolver.stop()

    asyncio.run(main())


async def ask_udp(port: int, packet: bytes) -> bytes:
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setblocking(False)
        await loop.sock_sendto(s, packet, ("127.0.0.1", port))
        return await asyncio.wait_for(loop.sock_recv(s, 4096), 2)


async def ask_tcp(port: int, packet: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(struct.pack(">H", len(packet)) + packet)
    await writer.drain()
    size = struct.unpack(">H", await asyncio.wait_for(reader.readexactly(2), 2))[0]
    data = await reader.readexactly(size)
    writer.close()
    return data


def rcode(packet: bytes) -> int:
    return packet[3] & 0x0F


def test_wire_helpers() -> None:
    q = query("Api.Example.com")
    assert question_name(q) == "api.example.com"
    assert question_name(q[:5]) is None
    assert question_name(b"") is None
    assert rcode(nxdomain(q)) == 3 and rcode(servfail(q)) == 2
    assert nxdomain(q)[:2] == q[:2]
    r = response(q, [a_record("192.0.2.7", 77), (28, 5, IPv6Address("2001:db8::1").packed), (5, 9, b"\x00")])
    assert answer_records(r) == [(ip_address("192.0.2.7"), 77), (ip_address("2001:db8::1"), 5)]
    assert answer_records(r[:20]) == []


def test_denied_name_gets_nxdomain_and_upstream_is_not_called() -> None:
    upstream, enforcer = Upstream([a_record("192.0.2.7")]), FakeEnforcer()

    async def scenario(_: FilteringResolver, port: int) -> None:
        assert rcode(await ask_udp(port, query("bad.example.com"))) == 3
        assert rcode(await ask_udp(port, query("unlisted.org"))) == 3

    run(scenario, FilteringResolver(RULES, enforcer, upstream))
    assert upstream.calls == 0 and enforcer.events == []


def test_allow_is_called_before_the_reply_is_sent() -> None:
    enforcer = FakeEnforcer()
    seen_at_send: list[list[tuple[str, str]]] = []

    def upstream(packet: bytes) -> bytes:
        return response(packet, [a_record("192.0.2.7"), a_record("192.0.2.8")])

    async def scenario(_: FilteringResolver, port: int) -> None:
        reply = await ask_udp(port, query("api.example.com"))
        seen_at_send.append(list(enforcer.events))
        assert [ip for ip, _ in answer_records(reply)] == [ip_address("192.0.2.7"), ip_address("192.0.2.8")]

    run(scenario, FilteringResolver(RULES, enforcer, upstream))
    assert seen_at_send == [[("allow", "192.0.2.7"), ("allow", "192.0.2.8")]]


def test_enforcer_failure_withholds_the_answer() -> None:
    enforcer = FakeEnforcer()
    enforcer.fail = True

    async def scenario(_: FilteringResolver, port: int) -> None:
        assert rcode(await ask_udp(port, query("api.example.com"))) == 2

    run(scenario, FilteringResolver(RULES, enforcer, Upstream([a_record("192.0.2.7")])))


def test_upstream_failure_gives_servfail() -> None:
    def upstream(packet: bytes) -> bytes:
        raise OSError("timeout")

    async def scenario(_: FilteringResolver, port: int) -> None:
        assert rcode(await ask_udp(port, query("api.example.com"))) == 2

    run(scenario, FilteringResolver(RULES, FakeEnforcer(), upstream))


def test_upstream_error_code_is_passed_through_and_nothing_is_learned() -> None:
    enforcer = FakeEnforcer()

    async def scenario(_: FilteringResolver, port: int) -> None:
        assert rcode(await ask_udp(port, query("api.example.com"))) == 3

    run(scenario, FilteringResolver(RULES, enforcer, Upstream([], rcode=3)))
    assert enforcer.events == []


def test_cname_chain_learns_the_final_addresses_and_judges_the_queried_name() -> None:
    enforcer = FakeEnforcer()
    cname = (5, 60, _name("edge.cdn.net"))

    async def scenario(_: FilteringResolver, port: int) -> None:
        reply = await ask_udp(port, query("www.example.com"))
        assert rcode(reply) == 0

    run(scenario, FilteringResolver(RULES, enforcer, Upstream([cname, a_record("198.51.100.4")])))
    assert enforcer.events == [("allow", "198.51.100.4")]


def test_malformed_packet_is_dropped_and_the_server_keeps_answering() -> None:
    async def scenario(_: FilteringResolver, port: int) -> None:
        loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setblocking(False)
            await loop.sock_sendto(s, b"\x01\x02\x03", ("127.0.0.1", port))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(loop.sock_recv(s, 4096), 0.3)
        assert rcode(await ask_udp(port, query("api.example.com"))) == 0

    run(scenario, FilteringResolver(RULES, FakeEnforcer(), Upstream([a_record("192.0.2.7")])))


def test_oversized_udp_answer_is_truncated_and_tcp_returns_it_whole() -> None:
    many = [a_record(f"192.0.2.{i}") for i in range(1, 60)]

    async def scenario(_: FilteringResolver, port: int) -> None:
        udp = await ask_udp(port, query("api.example.com"))
        assert udp[2] & 0x02 and len(udp) <= 512 and answer_records(udp) == []
        tcp = await ask_tcp(port, query("api.example.com"))
        assert not tcp[2] & 0x02 and len(answer_records(tcp)) == 59

    run(scenario, FilteringResolver(RULES, FakeEnforcer(), Upstream(many)))


def test_expired_addresses_are_revoked_once() -> None:
    clock, enforcer = Clock(), FakeEnforcer()
    resolver = FilteringResolver(
        RULES, enforcer, Upstream([a_record("192.0.2.7", 60)]), LearnedTable(clock), reap_interval=0.02
    )

    async def scenario(_: FilteringResolver, port: int) -> None:
        await ask_udp(port, query("api.example.com"))
        await asyncio.sleep(0.1)
        assert enforcer.events == [("allow", "192.0.2.7")]
        clock.now += 61
        await asyncio.sleep(0.15)

    run(scenario, resolver)
    assert enforcer.events == [("allow", "192.0.2.7"), ("revoke", "192.0.2.7")]


def test_same_address_is_opened_once_while_valid() -> None:
    enforcer = FakeEnforcer()

    async def scenario(_: FilteringResolver, port: int) -> None:
        await ask_udp(port, query("api.example.com"))
        await ask_udp(port, query("api.example.com"))

    run(scenario, FilteringResolver(RULES, enforcer, Upstream([a_record("192.0.2.7")])))
    assert enforcer.events == [("allow", "192.0.2.7")]


def test_each_matching_allow_rule_opens_its_own_ports_on_the_same_address() -> None:
    enforcer = FakeEnforcer()
    https = NameRule(True, "example.com", ("tcp",), ((443, 443),))
    http = NameRule(True, "api.example.com", ("tcp",), ((80, 80),))

    async def scenario(_: FilteringResolver, port: int) -> None:
        await ask_udp(port, query("api.example.com"))
        await ask_udp(port, query("api.example.com"))

    run(scenario, FilteringResolver((https, http), enforcer, Upstream([a_record("192.0.2.7")])))
    assert enforcer.events == [("allow", "192.0.2.7"), ("allow", "192.0.2.7")]
    assert enforcer.rules == [https, http]


def test_stop_frees_the_port() -> None:
    async def main() -> None:
        resolver = FilteringResolver(RULES, FakeEnforcer(), Upstream([]))
        port = await resolver.start()
        await resolver.stop()
        for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
            with socket.socket(socket.AF_INET, kind) as s:
                s.bind(("127.0.0.1", port))

    asyncio.run(main())
