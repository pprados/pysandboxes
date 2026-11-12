# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from ipaddress import ip_address

import pytest

from pysandboxes.egress_filter import (
    MAX_LEARNED_TTL,
    MIN_LEARNED_TTL,
    LearnedTable,
    NameRule,
    allowing_rules,
    clamp_ttl,
)


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("example.com", "example.com", True),
        ("example.com", "api.example.com", True),
        ("example.com", "notexample.com", False),
        ("example.com", "example.com.evil.org", False),
        ("=example.com", "example.com", True),
        ("=example.com", "api.example.com", False),
        ("*.example.com", "api.example.com", True),
        ("*.example.com", "example.com", False),
        ("*.example.com", "a.b.example.com", True),
        ("Example.COM.", "EXAMPLE.com", True),
    ],
)
def test_pattern_matching(pattern: str, name: str, expected: bool) -> None:
    assert NameRule(True, pattern).matches(name) is expected


def test_empty_name_matches_nothing() -> None:
    assert NameRule(True, "example.com").matches("") is False
    assert NameRule(True, "example.com").matches(".") is False


def test_a_matching_deny_before_the_allow_refuses_the_name() -> None:
    allow = NameRule(True, "example.com")
    rules = (NameRule(False, "bad.example.com"), allow)
    assert allowing_rules(rules, "bad.example.com") == []
    assert allowing_rules(rules, "ok.example.com") == [allow]


def test_every_allow_rule_matching_the_name_is_returned_in_order() -> None:
    https = NameRule(True, "example.com", ("tcp",), ((443, 443),))
    dns = NameRule(True, "api.example.com", ("udp",), ((53, 53),))
    assert allowing_rules((https, dns), "api.example.com") == [https, dns]
    assert allowing_rules((https, dns), "www.example.com") == [https]


def test_a_deny_stops_the_collection_of_the_allows_after_it() -> None:
    first = NameRule(True, "example.com", ("tcp",), ((443, 443),))
    deny = NameRule(False, "example.com")
    late = NameRule(True, "example.com", ("tcp",), ((80, 80),))
    assert allowing_rules((first, deny, late), "example.com") == [first]


def test_default_deny_is_empty() -> None:
    assert allowing_rules((NameRule(True, "example.com"),), "other.org") == []
    assert allowing_rules((), "example.com") == []


def test_a_rule_keeps_its_protocols_and_ports() -> None:
    rule = NameRule(True, "example.com", ("tcp",), ((443, 443), (8000, 8010)))
    assert rule.kinds == ("tcp",) and rule.ports == ((443, 443), (8000, 8010))
    assert NameRule(True, "example.com").kinds == ("tcp", "udp") and NameRule(True, "example.com").ports == ()


@pytest.mark.parametrize(("ttl", "expected"), [(0, 60), (59, 60), (60, 60), (600, 600), (3600, 3600), (86400, 3600)])
def test_ttl_clamped_to_60_and_3600(ttl: int, expected: int) -> None:
    assert (MIN_LEARNED_TTL, MAX_LEARNED_TTL) == (60, 3600)
    assert clamp_ttl(ttl) == expected


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_expiry_uses_injected_clock() -> None:
    clock = _Clock()
    table = LearnedTable(clock)
    ip = ip_address("192.0.2.7")
    assert table.learn([ip], 60) == [ip]
    assert table.allows(ip) is True
    clock.now += 59
    assert table.expired() == [] and table.allows(ip) is True
    clock.now += 2
    assert table.allows(ip) is False
    assert table.expired() == [ip]
    assert table.allows(ip) is False
    assert table.expired() == []


def test_relearn_extends_expiry_and_is_not_reported_as_new() -> None:
    clock = _Clock()
    table = LearnedTable(clock)
    ip = ip_address("192.0.2.7")
    table.learn([ip], 60)
    clock.now += 50
    assert table.learn([ip], 60) == []
    clock.now += 50
    assert table.allows(ip) is True
    assert table.expired() == []


def test_a_second_address_is_independent() -> None:
    clock = _Clock()
    table = LearnedTable(clock)
    first, second = ip_address("192.0.2.7"), ip_address("192.0.2.8")
    table.learn([first], 60)
    clock.now += 30
    table.learn([second], 3600)
    clock.now += 40
    assert table.expired() == [first]
    assert table.allows(second) is True
