# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import ipaddress
import re
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from pathlib import Path

import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.sb_types import ConfigLine

CONFIG = ConfigLine("net=test", Path("p"), 1)

ipv4 = st.builds(lambda a, p: ipaddress.ip_network((a, p), strict=False), st.integers(0, 2**32 - 1), st.integers(0, 32))
ipv6 = st.builds(
    lambda a, p: ipaddress.ip_network((a, p), strict=False), st.integers(0, 2**128 - 1), st.integers(0, 128)
)
networks = st.one_of(ipv4, ipv6)
ports = st.one_of(
    st.lists(st.integers(0, 65535), max_size=40, unique=True).map(tuple),
    st.builds(lambda a, n: range(a, min(a + n, 65536)), st.integers(0, 65535), st.integers(1, 65535)),
    st.just(range(65536)),
)
kinds = st.lists(st.sampled_from([Kind.TCP, Kind.UDP]), min_size=1, max_size=2, unique=True).map(tuple)
directions = st.lists(st.sampled_from(list(Direction)), min_size=1, max_size=2, unique=True).map(tuple)
rules = st.builds(
    lambda action, k, n, p, d: SocketRule(action, SocketMask(k, n, p), d, CONFIG),
    st.sampled_from(list(Action)),
    kinds,
    networks,
    ports,
    directions,
)
rulesets = st.lists(rules, max_size=4).map(tuple)
dns = st.lists(st.builds(IPv4Address, st.integers(0, 2**32 - 1)), max_size=2, unique=True)


@given(rulesets, dns, st.booleans())
def test_the_ruleset_is_a_closed_default_drop_filter_table(
    rs: tuple[SocketRule, ...], servers: list[IPv4Address], v6: bool
) -> None:
    out = rule_to_netfilter(rs, servers, v6)
    assert out[0] == "*filter" and out[-1] == "COMMIT" and out.count("COMMIT") == 1
    assert [line for line in out if line.startswith(":")] == [
        ":INPUT DROP [0:0]",
        ":FORWARD DROP [0:0]",
        ":OUTPUT DROP [0:0]",
    ]
    assert all(line.startswith("-A INPUT ") or line.startswith("-A OUTPUT ") for line in out[4:-1])
    assert "" not in out
    assert len(out) == len(set(out))


@given(rulesets, st.booleans())
def test_an_action_is_accept_or_reject_and_nothing_else(rs: tuple[SocketRule, ...], v6: bool) -> None:
    for line in rule_to_netfilter(rs, [], v6)[6:-1]:
        assert line.endswith(" -j ACCEPT") or line.endswith(" -j REJECT")


@given(rulesets, st.booleans())
def test_a_rule_of_the_other_ip_version_is_skipped(rs: tuple[SocketRule, ...], v6: bool) -> None:
    for line in rule_to_netfilter(rs, [], v6)[6:-1]:
        for token in re.findall(r"-d (\S+)", line):
            assert ipaddress.ip_network(token).version == (6 if v6 else 4)


@given(rulesets, st.booleans())
def test_a_multiport_match_takes_at_most_15_ports(rs: tuple[SocketRule, ...], v6: bool) -> None:
    for line in rule_to_netfilter(rs, [], v6):
        for token in re.findall(r"--dports (\S+)", line):
            assert len(token.split(",")) <= 15


@given(networks, directions, kinds)
def test_an_empty_port_field_matches_no_port(
    net: IPv4Network | IPv6Network, d: tuple[Direction, ...], k: tuple[Kind, ...]
) -> None:
    rule = SocketRule(Action.ALLOW, SocketMask(k, net, ()), d, CONFIG)
    for v6 in (False, True):
        assert rule_to_netfilter((rule,), [], v6) == rule_to_netfilter((), [], v6)


@given(networks, kinds)
def test_the_profile_order_is_kept_because_iptables_stops_at_the_first_match(
    net: IPv4Network | IPv6Network, k: tuple[Kind, ...]
) -> None:
    mask = SocketMask(k, net, (80,))
    allow = SocketRule(Action.ALLOW, mask, (Direction.OUT,), CONFIG)
    deny = SocketRule(Action.DENY, mask, (Direction.OUT,), CONFIG)
    v6 = isinstance(net, IPv6Network)
    first = rule_to_netfilter((allow, deny), [], v6)[6:-1]
    last = rule_to_netfilter((deny, allow), [], v6)[6:-1]
    assert [line.rsplit(" ", 1)[1] for line in first if "--dports 80" in line][:: len(k)] == ["ACCEPT", "REJECT"]
    assert [line.rsplit(" ", 1)[1] for line in last if "--dports 80" in line][:: len(k)] == ["REJECT", "ACCEPT"]


@given(networks)
def test_every_port_needs_no_multiport_and_a_range_is_not_a_list(net: IPv4Network | IPv6Network) -> None:
    v6 = isinstance(net, IPv6Network)
    every = rule_to_netfilter(
        (SocketRule(Action.ALLOW, SocketMask((Kind.TCP,), net, range(65536)), (Direction.OUT,), CONFIG),), [], v6
    )
    assert not any("multiport" in line for line in every)
    some = rule_to_netfilter(
        (SocketRule(Action.ALLOW, SocketMask((Kind.TCP,), net, range(20, 30)), (Direction.OUT,), CONFIG),), [], v6
    )
    assert any("--dports 20:29 " in line for line in some)


@given(st.lists(st.builds(IPv4Address, st.integers(0, 2**32 - 1)), min_size=1, max_size=3, unique=True))
def test_a_dns_server_is_reachable_only_in_the_ipv4_ruleset(servers: list[IPv4Address]) -> None:
    v4 = rule_to_netfilter((), servers, False)
    v6 = rule_to_netfilter((), servers, True)
    assert sum("--dport 53" in line for line in v4) == len(servers)
    assert not any("--dport 53" in line for line in v6)


def test_the_checks_have_teeth() -> None:
    """Negative control: an IPv6 address leaked into the IPv4 build is caught by the regex check."""
    leaked = "-A OUTPUT -p tcp -d ::1/128 -j ACCEPT"
    assert ipaddress.ip_network(re.findall(r"-d (\S+)", leaked)[0]).version == 6
    with pytest.raises(AssertionError):
        assert ipaddress.ip_network(re.findall(r"-d (\S+)", leaked)[0]).version == 4
