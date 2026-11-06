# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`RuntimeDns`: the filtering resolver of one sandbox, run on its own thread, forwarding to the host over TCP."""

import socket
import struct
import threading
from ipaddress import IPv4Address, IPv6Address
from typing import Iterator

import pytest
from pysandboxes.remote.runtime_dns import RuntimeDns

from pysandboxes.egress_filter import NameRule
from tests.unit_tests.test_egress_filter_resolver import a_record, query, rcode, response

RULES = (NameRule(True, "example.com", ("tcp",), ((443, 443),)),)


class Enforcer:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def allow(self, ip: IPv4Address | IPv6Address, rule: NameRule, ttl: int) -> None:
        self.events.append(("allow", str(ip)))

    def revoke(self, ip: IPv4Address | IPv6Address, rule: NameRule) -> None:
        self.events.append(("revoke", str(ip)))


class Upstream:
    """A DNS server over TCP on host loopback: what the resolver of the host is for the filter."""

    def __init__(self) -> None:
        self.queries: list[bytes] = []
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self._server.settimeout(0.1)
        self.port: int = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                size = struct.unpack(">H", conn.recv(2))[0]
                packet = conn.recv(size)
                self.queries.append(packet)
                reply = response(packet, [a_record("192.0.2.7", 300)])
                conn.sendall(struct.pack(">H", len(reply)) + reply)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._server.close()


@pytest.fixture
def upstream() -> Iterator[Upstream]:
    server = Upstream()
    yield server
    server.close()


def ask(port: int, packet: bytes) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        s.sendto(packet, ("127.0.0.1", port))
        return s.recvfrom(4096)[0]


def service(upstream: Upstream) -> RuntimeDns:
    return RuntimeDns(RULES, [IPv4Address("127.0.0.1")], upstream_port=upstream.port)


def test_start_returns_the_ephemeral_port_and_stop_releases_it(upstream: Upstream) -> None:
    dns = service(upstream)

    port = dns.start()
    dns.stop()

    assert port > 0
    for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
        with socket.socket(socket.AF_INET, kind) as s:
            s.bind(("127.0.0.1", port))


def test_an_allowed_name_is_forwarded_over_tcp_and_opened_before_the_answer(upstream: Upstream) -> None:
    enforcer, dns = Enforcer(), service(upstream)
    port = dns.start()
    try:
        dns.attach(enforcer)
        reply = ask(port, query("api.example.com"))
    finally:
        dns.stop()

    assert rcode(reply) == 0 and enforcer.events == [("allow", "192.0.2.7")]
    assert len(upstream.queries) == 1


def test_a_denied_name_never_reaches_the_host_resolver(upstream: Upstream) -> None:
    dns = service(upstream)
    port = dns.start()
    try:
        dns.attach(Enforcer())
        reply = ask(port, query("other.org"))
    finally:
        dns.stop()

    assert rcode(reply) == 3 and upstream.queries == []


def test_before_an_enforcer_is_attached_the_answer_is_withheld(upstream: Upstream) -> None:
    dns = service(upstream)
    port = dns.start()
    try:
        reply = ask(port, query("api.example.com"))
    finally:
        dns.stop()

    assert rcode(reply) == 2


def test_an_unreachable_host_resolver_gives_servfail_and_opens_nothing() -> None:
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    closed_port = free.getsockname()[1]
    free.close()
    enforcer = Enforcer()
    dns = RuntimeDns(RULES, [IPv4Address("127.0.0.1")], upstream_port=closed_port, upstream_timeout=0.3)
    port = dns.start()
    try:
        dns.attach(enforcer)
        reply = ask(port, query("api.example.com"))
    finally:
        dns.stop()

    assert rcode(reply) == 2 and enforcer.events == []


def test_with_no_host_resolver_known_the_answer_is_withheld() -> None:
    enforcer = Enforcer()
    dns = RuntimeDns(RULES, [])
    port = dns.start()
    try:
        dns.attach(enforcer)
        reply = ask(port, query("api.example.com"))
    finally:
        dns.stop()

    assert rcode(reply) == 2 and enforcer.events == []


def test_the_second_host_resolver_is_tried_when_the_first_fails(upstream: Upstream) -> None:
    enforcer = Enforcer()
    # The upstream listens on 127.0.0.1 only: the connection to 127.0.0.2 is refused, the first one fails.
    dns = RuntimeDns(
        RULES,
        [IPv4Address("127.0.0.2"), IPv4Address("127.0.0.1")],
        upstream_port=upstream.port,
        upstream_timeout=0.3,
    )
    port = dns.start()
    try:
        dns.attach(enforcer)
        reply = ask(port, query("api.example.com"))
    finally:
        dns.stop()

    assert rcode(reply) == 0 and enforcer.events == [("allow", "192.0.2.7")]


def test_stop_ends_the_thread_and_is_idempotent(upstream: Upstream) -> None:
    dns = service(upstream)
    dns.start()
    before = threading.active_count()

    dns.stop()
    dns.stop()

    assert threading.active_count() == before - 1
