# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=` through the whole profile parser: both implementations stay reachable by one parameter."""

import socket
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.egress_filter import DEFAULT_NET_RESOLVE, NameRule
from pysandboxes.py_sandbox import parse_config
from pysandboxes.sb_types import ConfigLine

LITERAL = "net=ALLOW|TCP|203.0.113.0/24|443|OUT"
NAMED = "net=ALLOW|TCP|api.example.com|443|OUT"


def _parse(*rules: str) -> object:
    config = [ConfigLine(rule, Path("p.profile"), n) for n, rule in enumerate(rules, 1)]
    return parse_config(config, Path("p.profile"), envs={})


@pytest.fixture(autouse=True)
def no_resolution(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def fake(host: str, port: object = 0, *args: object, **kwargs: object) -> list:
        asked.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.9", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return asked


def test_empty_rules_carry_the_default_and_no_name_rule() -> None:
    assert EmptyRules.net_resolve == DEFAULT_NET_RESOLVE and EmptyRules.name_rules == ()


def test_pinned_is_the_current_behaviour_the_name_is_resolved_at_parse_time(no_resolution: list[str]) -> None:
    rules = _parse("os-sandbox=subprocess", NAMED)

    assert rules.net_resolve == "pinned" and rules.name_rules == ()  # type: ignore[attr-defined]
    assert no_resolution == ["api.example.com"] and "api.example.com" in rules.pin_dns  # type: ignore[attr-defined]


def test_pinned_can_be_asked_for_explicitly(no_resolution: list[str]) -> None:
    rules = _parse("os-sandbox=subprocess", "net-resolve=pinned", NAMED)

    assert rules.net_resolve == "pinned" and no_resolution == ["api.example.com"]  # type: ignore[attr-defined]


def test_runtime_keeps_the_name_and_resolves_nothing_at_parse_time(no_resolution: list[str]) -> None:
    rules = _parse("os-sandbox=unshare", "net-resolve=runtime", NAMED, LITERAL)

    assert rules.net_resolve == "runtime"  # type: ignore[attr-defined]
    assert rules.name_rules == (NameRule(True, "api.example.com", ("tcp",), ((443, 443),)),)  # type: ignore[attr-defined]
    assert no_resolution == [] and dict(rules.pin_dns) == {}  # type: ignore[attr-defined]
    assert [str(r.mask.network) for r in rules.socket_rules] == ["203.0.113.0/24"]  # type: ignore[attr-defined]


def test_runtime_on_a_provider_without_an_enforcer_is_a_config_error() -> None:
    with pytest.raises(ConfigSyntaxError) as raised:
        _parse("os-sandbox=none", "net-resolve=runtime", NAMED)

    assert "net-resolve=runtime is not supported by the 'none' provider" in " ".join(raised.value.errors)


def test_an_unknown_mode_is_a_config_error() -> None:
    with pytest.raises(ConfigSyntaxError) as raised:
        _parse("os-sandbox=subprocess", "net-resolve=dynamic")

    assert "Invalid value 'dynamic' for net-resolve" in " ".join(raised.value.errors)
