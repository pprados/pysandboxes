# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`RuntimeDnsSession`: the life of the filtering resolver, shared by the providers that drive a network namespace."""

from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.egress_filter import NameRule
from pysandboxes.remote import runtime_dns as rd
from pysandboxes.remote.runtime_dns import RuntimeDnsSession

UPSTREAM = IPv4Address("198.51.100.53")
NAMES = (NameRule(True, "example.com", ("tcp",), ((443, 443),)),)
RUNTIME = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES)


class FakeDns:
    instances: list["FakeDns"] = []

    def __init__(self, rules: Any, servers: Any, **_: Any) -> None:
        self.rules, self.servers = rules, list(servers)
        self.started = self.stopped = 0
        self.enforcer: Any = None
        FakeDns.instances.append(self)

    def start(self) -> int:
        self.started += 1
        return 15353

    def attach(self, enforcer: Any) -> None:
        self.enforcer = enforcer

    def stop(self) -> None:
        self.stopped += 1


@pytest.fixture(autouse=True)
def host(monkeypatch: pytest.MonkeyPatch) -> type[FakeDns]:
    FakeDns.instances = []
    monkeypatch.setattr(rd, "RuntimeDns", FakeDns)
    monkeypatch.setattr(rd, "which_command", lambda name: Path("/usr/bin") / name)
    monkeypatch.setattr(rd, "get_upstream_dns", lambda: [UPSTREAM])
    return FakeDns


def test_a_pinned_profile_starts_no_resolver(host: type[FakeDns]) -> None:
    session = RuntimeDnsSession()

    assert session.start(EmptyRules) is None and not session.running
    assert host.instances == []


def test_a_runtime_profile_starts_the_resolver_on_the_rules_and_the_ipv4_resolvers_of_the_host(
    host: type[FakeDns], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rd, "get_upstream_dns", lambda: [UPSTREAM, ip_address("2001:db8::53")])
    session = RuntimeDnsSession()

    port = session.start(RUNTIME)

    assert port == 15353 and session.running
    assert host.instances[0].rules == NAMES and host.instances[0].servers == [UPSTREAM]


@pytest.mark.parametrize("missing", ["nsenter", "iptables"])
def test_a_runtime_profile_needs_nsenter_and_iptables_on_the_host(
    host: type[FakeDns], monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setattr(rd, "which_command", lambda name: None if name == missing else Path("/usr/bin") / name)

    with pytest.raises(SandBoxError, match=missing):
        RuntimeDnsSession().start(RUNTIME)

    assert host.instances == []


def test_a_host_with_no_ipv4_resolver_is_an_error_not_a_silent_servfail(
    host: type[FakeDns], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rd, "get_upstream_dns", lambda: [ip_address("2001:db8::53")])

    with pytest.raises(SandBoxError, match="no IPv4 resolver"):
        RuntimeDnsSession().start(RUNTIME)

    assert host.instances == []


def test_a_restart_stops_the_previous_resolver_before_starting_another(host: type[FakeDns]) -> None:
    session = RuntimeDnsSession()

    session.start(RUNTIME)
    session.start(RUNTIME)

    assert [d.stopped for d in host.instances] == [1, 0]


def test_restarting_with_a_pinned_profile_stops_the_resolver_and_starts_none(host: type[FakeDns]) -> None:
    session = RuntimeDnsSession()
    session.start(RUNTIME)

    assert session.start(EmptyRules) is None

    assert host.instances[0].stopped == 1 and not session.running


def test_the_enforcer_is_attached_to_the_pid_that_holds_the_network_namespace(host: type[FakeDns]) -> None:
    session = RuntimeDnsSession()
    session.start(RUNTIME)

    session.attach(4242)

    assert host.instances[0].enforcer._prefix == [
        "/usr/bin/nsenter",
        "-t",
        "4242",
        "-U",
        "-n",
        "--preserve-credentials",
        "/usr/bin/iptables",
    ]


def test_attaching_without_a_resolver_does_nothing(host: type[FakeDns]) -> None:
    RuntimeDnsSession().attach(4242)

    assert host.instances == []


def test_stopping_closes_the_resolver_once_and_forgets_it(host: type[FakeDns]) -> None:
    session = RuntimeDnsSession()
    session.start(RUNTIME)

    session.stop()
    session.stop()

    assert host.instances[0].stopped == 1 and not session.running
