# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from ipaddress import IPv4Address, IPv4Network

from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.netfilter import rule_to_netfilter, runtime_netfilter

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
