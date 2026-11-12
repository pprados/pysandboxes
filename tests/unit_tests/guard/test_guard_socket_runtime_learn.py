# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime`: the guard of the sandboxed process learns an address from its own resolution of a name."""

import socket
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

import pysandboxes.guard_socket as gs
from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.egress_filter import MAX_LEARNED_TTL, NameRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLine

HTTPS = NameRule(True, "example.com", ("tcp",), ((443, 443),))
DENIED = NameRule(False, "bad.example.com")


class Dns:
    """What the filtering resolver answers: the addresses of a name, changeable between two queries."""

    def __init__(self) -> None:
        self.answers: dict[str, list[str]] = {}
        self.calls = 0

    def __call__(self, host: str, port: Any = 0, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> Any:
        self.calls += 1
        if host not in self.answers:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in self.answers[host]]


class Clock:
    now = 5000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> Iterator[Dns]:
    fake = Dns()
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    monkeypatch.setattr(gs, "_rules_loaded", True)
    monkeypatch.setattr(gs, "_rules", ())
    monkeypatch.setattr(gs, "_pin_dns", ImmutableDict({}))
    monkeypatch.setattr(gs, "_learned", {})
    monkeypatch.setattr(gs, "_name_rules", ())
    gs.getaddrinfo.cache_clear()
    yield fake
    gs.getaddrinfo.cache_clear()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(gs, "_clock", fake)
    return fake


def arm(*rules: NameRule) -> None:
    gs.set_name_rules(rules)


def check(host: str, port: int = 443, kind: Kind = Kind.TCP) -> list:
    return gs._check_address_with_rules(gs._rules, kind, (host, port), Direction.OUT)


def test_an_address_the_resolution_of_an_allowed_name_returned_is_allowed(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)

    assert check("api.example.com") == [ip_address("192.0.2.7")]


def test_nothing_is_learned_without_name_rules_so_the_default_policy_refuses(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("api.example.com")


def test_a_name_the_rules_do_not_name_is_refused(dns: Dns) -> None:
    dns.answers["other.org"] = ["192.0.2.9"]
    arm(HTTPS)

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("other.org")


def test_a_denied_name_is_never_learned_even_if_it_resolves(dns: Dns) -> None:
    dns.answers["bad.example.com"] = ["192.0.2.8"]
    arm(DENIED, HTTPS)

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("bad.example.com")
    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.8")


def test_the_protocol_and_the_port_of_the_name_rule_are_kept(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)
    check("api.example.com")

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.7", port=80)
    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.7", kind=Kind.UDP)
    assert check("192.0.2.7") == [ip_address("192.0.2.7")]


def test_a_literal_address_is_allowed_after_the_program_resolved_the_name_itself(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)
    infos = gs._wrap_socket_getaddrinfo(dns)("api.example.com", 443)

    assert infos[0][4][0] == "192.0.2.7"
    assert check("192.0.2.7") == [ip_address("192.0.2.7")]


def test_gethostbyname_and_its_extended_form_learn_too(dns: Dns) -> None:
    arm(HTTPS)
    gs._wrap_socket_gethostbyname(lambda name: "192.0.2.7")("api.example.com")
    gs._wrap_socket_gethostbyname_ex(lambda name: (name, [], ["192.0.2.8", "192.0.2.9"]))("api.example.com")

    for ip in ("192.0.2.7", "192.0.2.8", "192.0.2.9"):
        assert check(ip) == [ip_address(ip)]


def test_a_literal_address_nobody_resolved_stays_refused(dns: Dns) -> None:
    arm(HTTPS)

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.7")


def test_a_learned_address_expires_after_the_longest_ttl(dns: Dns, clock: Clock) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)
    check("api.example.com")
    clock.now += MAX_LEARNED_TTL - 1
    assert check("192.0.2.7") == [ip_address("192.0.2.7")]

    clock.now += 2

    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.7")


def test_a_name_whose_addresses_change_is_resolved_again_each_time_not_served_from_a_cache(dns: Dns) -> None:
    arm(HTTPS)
    dns.answers["api.example.com"] = ["192.0.2.7"]
    assert check("api.example.com") == [ip_address("192.0.2.7")]

    dns.answers["api.example.com"] = ["192.0.2.99"]

    assert check("api.example.com") == [ip_address("192.0.2.99")]
    assert dns.calls == 2


def test_a_static_deny_keeps_precedence_over_a_learned_address(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)
    deny = SocketRule(
        Action.DENY,
        SocketMask((Kind.TCP,), ip_network("192.0.2.0/24"), range(65536)),
        (Direction.OUT,),
        ConfigLine("net=DENY|TCP|192.0.2.0/24|*|OUT", Path(), 0),
    )

    with pytest.raises(RuleSocketConnectionRefusedError, match=r"by rule 'net=DENY\|TCP\|192\.0\.2\.0/24"):
        gs._check_address_with_rules((deny,), Kind.TCP, ("api.example.com", 443), Direction.OUT)


def test_every_allowing_rule_of_a_name_contributes_its_own_ports(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    http = NameRule(True, "api.example.com", ("tcp",), ((80, 80), (8000, 8002)))
    arm(HTTPS, http)
    check("api.example.com")

    for port in (80, 443, 8001):
        assert check("192.0.2.7", port=port) == [ip_address("192.0.2.7")]
    with pytest.raises(RuleSocketConnectionRefusedError):
        check("192.0.2.7", port=8003)


def test_a_rule_without_port_opens_every_port(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(NameRule(True, "example.com", ("tcp", "udp")))
    check("api.example.com")

    assert check("192.0.2.7", port=1) and check("192.0.2.7", port=65535, kind=Kind.UDP)


def test_deactivating_the_guard_forgets_the_names_and_what_was_learned(dns: Dns) -> None:
    dns.answers["api.example.com"] = ["192.0.2.7"]
    arm(HTTPS)
    check("api.example.com")
    deactivate: Callable[[], None] = gs._deactivate_guard_sockets

    deactivate()

    assert gs._name_rules == () and gs._learned == {}
