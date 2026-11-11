# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=pinned|runtime`: the profile key that picks how the host names of `net=` rules are resolved."""

import socket
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes import guard_socket
from pysandboxes.egress_filter import DEFAULT_NET_RESOLVE, NameRule
from pysandboxes.guard_provider import check_net_resolve_provider, parse_net_resolve
from pysandboxes.guard_socket import parse_name_rules
from pysandboxes.sb_types import ConfigLine


def _lines(*rules: str) -> list[ConfigLine]:
    return [ConfigLine(rule, Path("p"), n) for n, rule in enumerate(rules, 1)]


def test_the_default_is_one_named_constant_and_other_rules_pass_through() -> None:
    errors: list = []

    mode, others = parse_net_resolve(_lines("py-sandbox=true"), errors)

    assert (mode, [r.rule for r in others], errors) == (DEFAULT_NET_RESOLVE, ["py-sandbox=true"], [])


def test_the_current_implementation_stays_the_value_used_when_the_key_is_absent() -> None:
    assert DEFAULT_NET_RESOLVE == "pinned"


@pytest.mark.parametrize(("value", "expected"), [("runtime", "runtime"), (" PINNED ", "pinned")])
def test_a_known_mode_is_accepted_and_consumed(value: str, expected: str) -> None:
    errors: list = []

    mode, others = parse_net_resolve(_lines(f"net-resolve={value}", "a=b"), errors)

    assert (mode, [r.rule for r in others], errors) == (expected, ["a=b"], [])


def test_the_last_line_wins() -> None:
    mode, _ = parse_net_resolve(_lines("net-resolve=runtime", "net-resolve=pinned"), [])

    assert mode == "pinned"


@pytest.mark.parametrize("value", ["dynamic", "", "auto"])
def test_an_unknown_mode_is_an_error(value: str) -> None:
    errors: list = []

    mode, _ = parse_net_resolve(_lines(f"net-resolve={value}"), errors)

    assert mode == DEFAULT_NET_RESOLVE
    assert len(errors) == 1 and "net-resolve" in errors[0][0] and "pinned" in errors[0][0]


def test_pinned_is_accepted_by_every_provider() -> None:
    errors: list = []

    check_net_resolve_provider("pinned", "qemu", Path("p"), errors)

    assert errors == []


@pytest.mark.parametrize("provider", ["unshare", "bwrap", "gvisor", "firejail", "qemu", "qemu-microvm", "subprocess"])
def test_runtime_is_accepted_by_the_providers_with_an_enforcer(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.geteuid", lambda: 0)
    errors: list = []

    check_net_resolve_provider("runtime", provider, Path("p"), errors)

    assert errors == []


def test_runtime_under_firejail_is_an_error_without_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    errors: list = []

    check_net_resolve_provider("runtime", "firejail", Path("p"), errors)

    assert len(errors) == 1 and "needs root" in errors[0][0]


@pytest.mark.parametrize("provider", ["landlock", "none", "sandbox-exec", "appcontainer"])
def test_runtime_is_an_error_for_a_provider_without_an_enforcer(provider: str) -> None:
    errors: list = []

    check_net_resolve_provider("runtime", provider, Path("p"), errors)

    assert len(errors) == 1
    assert provider in errors[0][0] and "unshare" in errors[0][0] and "net-resolve=pinned" in errors[0][0]


def _names(*rules: str) -> tuple[tuple[NameRule, ...], list[str], list]:
    errors: list = []
    name_rules, others = parse_name_rules(_lines(*rules), errors)
    return name_rules, [r.rule for r in others], errors


def test_a_host_name_rule_becomes_a_name_rule_and_is_consumed() -> None:
    name_rules, others, errors = _names("net=ALLOW|TCP|api.example.com|443|OUT")

    assert name_rules == (NameRule(True, "api.example.com", ("tcp",), ((443, 443),)),)
    assert others == [] and errors == []


def test_lines_that_are_not_host_names_pass_through_untouched() -> None:
    lines = ["net=ALLOW|TCP|203.0.113.0/24|443|OUT", "net=DENY|*|*|*|IN,OUT", "py-sandbox=true", "net=bad"]

    name_rules, others, errors = _names(*lines)

    assert name_rules == () and others == lines and errors == []


@pytest.mark.parametrize(
    ("ports", "expected"),
    [
        ("443", ((443, 443),)),
        ("80,443", ((80, 80), (443, 443))),
        ("8000-8010", ((8000, 8010),)),
        ("80,8000-8002,8004", ((80, 80), (8000, 8002), (8004, 8004))),
        ("*", ()),
    ],
)
def test_ports_become_inclusive_ranges_and_star_means_every_port(ports: str, expected: tuple) -> None:
    name_rules, _, errors = _names(f"net=ALLOW|TCP|example.com|{ports}|OUT")

    assert errors == [] and name_rules[0].ports == expected


@pytest.mark.parametrize(
    ("kinds", "expected"), [("TCP", ("tcp",)), ("UDP", ("udp",)), ("TCP,UDP", ("tcp", "udp")), ("*", ("tcp", "udp"))]
)
def test_kinds_become_protocol_names(kinds: str, expected: tuple[str, ...]) -> None:
    name_rules, _, errors = _names(f"net=ALLOW|{kinds}|example.com|53|OUT")

    assert errors == [] and name_rules[0].kinds == expected


@pytest.mark.parametrize("pattern", ["example.com", "=example.com", "*.example.com", "a-b.example.com"])
def test_the_name_patterns_are_accepted(pattern: str) -> None:
    name_rules, _, errors = _names(f"net=ALLOW|TCP|{pattern}|443|OUT")

    assert errors == [] and name_rules[0].pattern == pattern


@pytest.mark.parametrize("pattern", ["bad name", "exa$mple.com", "*example.com", "a..b", "=", "*."])
def test_a_malformed_name_is_an_error(pattern: str) -> None:
    name_rules, _, errors = _names(f"net=ALLOW|TCP|{pattern}|443|OUT")

    assert name_rules == () and len(errors) == 1 and f"|{pattern}|" in errors[0][0]


def test_deny_rules_come_before_allow_rules_as_in_the_pinned_ordering() -> None:
    name_rules, _, _ = _names(
        "net=ALLOW|TCP|example.com|443|OUT",
        "net=DENY|*|bad.example.com|*|OUT",
        "net=ALLOW|TCP|other.org|443|OUT",
    )

    assert [r.allow for r in name_rules] == [False, True, True]
    assert [r.pattern for r in name_rules] == ["bad.example.com", "example.com", "other.org"]


def test_a_name_rule_that_cannot_apply_to_outgoing_traffic_is_an_error() -> None:
    name_rules, _, errors = _names("net=ALLOW|TCP|example.com|443|IN")

    assert name_rules == () and len(errors) == 1 and "OUT" in errors[0][0]


def test_an_allow_that_opens_no_port_or_no_socket_kind_is_dropped_not_fatal() -> None:
    name_rules, others, errors = _names("net=ALLOW|TCP|example.com||OUT")

    assert name_rules == () and others == [] and errors == []


def test_an_invalid_action_is_an_error() -> None:
    _, _, errors = _names("net=PERMIT|TCP|example.com|443|OUT")

    assert len(errors) == 1 and "ALLOW" in errors[0][0]


def test_the_remaining_lines_never_reach_the_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a host name was resolved at parse time")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    _, others = parse_name_rules(
        _lines("net=ALLOW|TCP|api.example.com|443|OUT", "net=ALLOW|TCP|203.0.113.0/24|443|OUT"), []
    )

    socket_rules, ignored, pin_dns = guard_socket.parse_rules(others, [])

    assert len(socket_rules) == 1 and dict(pin_dns) == {} and ignored == []
