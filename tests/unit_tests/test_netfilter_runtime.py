# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from ipaddress import IPv4Address, IPv4Network, IPv6Network

from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.netfilter import rule_to_netfilter, runtime_netfilter, runtime_netfilter6

GATEWAY = IPv4Address("10.0.2.2")
SLIRP_DNS = IPv4Address("10.0.2.3")


def socket_rule(action: Action, network: str, port: int) -> SocketRule:
    return SocketRule(
        action,
        SocketMask((Kind.TCP,), IPv4Network(network), (port,)),
        (Direction.OUT,),
        None,  # type: ignore[arg-type]
    )


def build(rules: tuple[SocketRule, ...] = ()) -> list[str]:
    return runtime_netfilter(rules, 15353, GATEWAY, SLIRP_DNS)


def test_default_policy_is_drop_and_the_learned_chain_is_declared() -> None:
    rules = build()
    assert ":OUTPUT DROP [0:0]" in rules and ":INPUT DROP [0:0]" in rules
    assert ":LEARNED - [0:0]" in rules[: rules.index("*nat") if "*nat" in rules else len(rules)]


def test_dns_is_accepted_only_towards_the_resolver_port_of_the_gateway() -> None:
    rules = build()
    for proto in ("udp", "tcp"):
        assert f"-A OUTPUT -p {proto} -d 10.0.2.2/32 --dport 15353 -m conntrack --ctstate NEW -j ACCEPT" in rules
    assert not [r for r in rules if "--dport 53 " in r and "ACCEPT" in r]
    assert not [r for r in rules if "10.0.2.3" in r and r.startswith("-A OUTPUT") and "ACCEPT" in r]


def test_no_resolver_other_than_the_gateway_port_is_ever_accepted() -> None:
    accepted = [r for r in build() if r.startswith("-A OUTPUT") and "--dport" in r and r.endswith("ACCEPT")]
    assert all("10.0.2.2/32 --dport 15353" in r for r in accepted)


def test_dns_to_the_slirp_address_is_redirected_by_the_nat_table() -> None:
    rules = build()
    nat = rules[rules.index("*nat") :]
    assert nat[-1] == "COMMIT" and ":OUTPUT ACCEPT [0:0]" in nat
    for proto in ("udp", "tcp"):
        assert f"-A OUTPUT -p {proto} -d 10.0.2.3/32 --dport 53 -j DNAT --to-destination 10.0.2.2:15353" in nat


def test_the_learned_chain_is_jumped_to_after_the_static_rules() -> None:
    deny = socket_rule(Action.DENY, "203.0.113.0/24", 443)
    allow = socket_rule(Action.ALLOW, "198.51.100.0/24", 443)
    rules = build((deny, allow))
    filter_table = rules[: rules.index("*nat")]
    jump = filter_table.index("-A OUTPUT -j LEARNED")
    static = [i for i, r in enumerate(filter_table) if "203.0.113.0/24" in r or "198.51.100.0/24" in r]
    assert static and all(i < jump for i in static)
    assert filter_table[jump + 1] == "COMMIT"


def test_the_filter_part_keeps_what_the_pinned_builder_makes_for_the_same_rules() -> None:
    allow = socket_rule(Action.ALLOW, "198.51.100.0/24", 443)
    pinned = rule_to_netfilter((allow,), [], is_ipv6=False)
    runtime = build((allow,))
    assert [r for r in pinned if "198.51.100.0/24" in r] == [r for r in runtime if "198.51.100.0/24" in r]
    assert pinned[:6] == [r for r in runtime if r != ":LEARNED - [0:0]"][:6]


def socket_rule6(action: Action, network: str, port: int) -> SocketRule:
    return SocketRule(
        action,
        SocketMask((Kind.TCP,), IPv6Network(network), (port,)),
        (Direction.OUT,),
        None,  # type: ignore[arg-type]
    )


def test_the_ipv6_ruleset_drops_by_default_and_declares_the_learned_chain_once() -> None:
    rules = runtime_netfilter6(())
    assert rules[0] == "*filter" and rules[-1] == "COMMIT" and rules.count("COMMIT") == 1
    assert ":OUTPUT DROP [0:0]" in rules and ":INPUT DROP [0:0]" in rules and ":FORWARD DROP [0:0]" in rules
    assert rules.count(":LEARNED - [0:0]") == 1 and rules[-2] == "-A OUTPUT -j LEARNED"


def test_the_ipv6_ruleset_opens_no_resolver_and_no_nat() -> None:
    rules = runtime_netfilter6(())
    assert "*nat" not in rules and not [r for r in rules if "--dport 53" in r or "DNAT" in r]


def test_router_and_neighbour_discovery_are_accepted_or_the_interface_never_gets_an_address() -> None:
    rules = runtime_netfilter6(())
    for kind in (134, 135, 136):
        assert f"-A INPUT -p ipv6-icmp --icmpv6-type {kind} -j ACCEPT" in rules
    for kind in (133, 135, 136):
        assert f"-A OUTPUT -p ipv6-icmp --icmpv6-type {kind} -j ACCEPT" in rules
    assert not [r for r in rules if "icmpv6-type" in r and r.startswith("-A OUTPUT") and "134" in r]


def test_a_static_ipv6_deny_comes_before_the_learned_chain() -> None:
    rules = runtime_netfilter6((socket_rule6(Action.DENY, "2001:db8::/32", 443),))
    deny = next(i for i, r in enumerate(rules) if "2001:db8::/32" in r and r.endswith("REJECT"))
    assert deny < rules.index("-A OUTPUT -j LEARNED")


def test_the_ipv6_ruleset_ignores_ipv4_rules() -> None:
    rules = runtime_netfilter6((socket_rule(Action.ALLOW, "192.0.2.0/24", 443),))
    assert not [r for r in rules if "192.0.2" in r]
