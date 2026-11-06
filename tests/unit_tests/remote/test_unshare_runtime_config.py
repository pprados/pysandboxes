# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`UnshareSSEDaemon` with `net-resolve=runtime`: the configuration, and the life of the filtering resolver."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.egress_filter import NameRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.netfilter import rule_to_netfilter, runtime_netfilter
from pysandboxes.remote import unshare_sse_daemon as usd
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon
from pysandboxes.sb_types import ConfigLine

GATEWAY, SLIRP_DNS = IPv4Address("10.0.2.2"), IPv4Address("10.0.2.3")
UPSTREAM = IPv4Address("198.51.100.53")
NAMES = (NameRule(True, "example.com", ("tcp",), ((443, 443),)),)


def _socket_rule(network: str, rule: str) -> SocketRule:
    return SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), IPv4Network(network), (443,)),
        (Direction.OUT,),
        ConfigLine(rule, Path("p"), 1),
    )


STATIC = _socket_rule("203.0.113.0/24", "net=ALLOW|TCP|203.0.113.0/24|443|OUT")
PINNED_NAME = _socket_rule("192.0.2.7/32", "net=ALLOW|TCP|api.example.com|443|OUT")


@pytest.fixture(autouse=True)
def host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usd, "which_command", lambda name: Path("/usr/bin") / name)
    monkeypatch.setattr(usd, "get_upstream_dns", lambda: [UPSTREAM])
    monkeypatch.setattr(usd.os.path, "exists", lambda path: False)


def _prepare(rules: Any, port: int | None = None) -> Any:
    config, _ = UnshareSSEDaemon("tok")._prepare_unshare_config(rules, Path("/tmp/pipe"), "/tmp/root", port)
    return config


def test_pinned_keeps_the_resolver_of_the_host_the_pinned_hosts_and_the_static_ruleset() -> None:
    rules = EmptyRules._replace(socket_rules=(STATIC, PINNED_NAME))

    config = _prepare(rules)

    assert config.dns_servers == [str(SLIRP_DNS), str(UPSTREAM)]
    assert config.hosts == ["192.0.2.7 api.example.com"]
    assert config.netfilter_rules == rule_to_netfilter(rules.socket_rules, [SLIRP_DNS, UPSTREAM], is_ipv6=False)


def test_runtime_has_only_the_slirp_dns_and_never_the_resolver_of_the_host() -> None:
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES, socket_rules=(STATIC,))

    config = _prepare(rules, 15353)

    assert config.dns_servers == [str(SLIRP_DNS)]
    assert not [line for line in config.netfilter_rules if str(UPSTREAM) in line]


def test_runtime_writes_no_pinned_host_entry() -> None:
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES, socket_rules=(STATIC, PINNED_NAME))

    assert _prepare(rules, 15353).hosts == []


def test_runtime_ruleset_is_the_runtime_builder_with_the_port_the_resolver_bound() -> None:
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES, socket_rules=(STATIC,))

    config = _prepare(rules, 15353)

    assert config.netfilter_rules == runtime_netfilter(rules.socket_rules, 15353, GATEWAY, SLIRP_DNS)
    assert (
        "-A OUTPUT -p udp -d 10.0.2.3/32 --dport 53 -j DNAT --to-destination 10.0.2.2:15353" in config.netfilter_rules
    )


def test_runtime_without_the_resolver_port_is_an_error_not_a_silent_pinned_ruleset() -> None:
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES)

    with pytest.raises(SandBoxError, match="resolver port"):
        _prepare(rules)


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def start(self, all_rules: Any) -> int:
        self.calls.append(("start", all_rules))
        return 15353

    def attach(self, pid: int) -> None:
        self.calls.append(("attach", pid))

    def stop(self) -> None:
        self.calls.append(("stop", None))


def test_the_daemon_owns_one_resolver_session() -> None:
    from pysandboxes.remote.runtime_dns import RuntimeDnsSession

    assert isinstance(UnshareSSEDaemon("tok")._dns_session, RuntimeDnsSession)


def test_the_end_of_a_one_shot_run_stops_the_resolver_through_kill_slirp() -> None:
    daemon = UnshareSSEDaemon("tok")
    session = FakeSession()
    daemon._dns_session = session  # type: ignore[assignment]

    daemon._kill_slirp()

    assert ("stop", None) in session.calls
