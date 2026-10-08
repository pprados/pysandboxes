# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from typing import Iterable, List, Union

from .guard_socket import Action, Direction, Kind, SocketRules

# The multiport match takes at most 15 ports.
_MULTIPORT_MAX = 15


def _build_port(rule_ports_list: Union[Iterable[int], range]) -> str:
    if isinstance(rule_ports_list, range):
        if rule_ports_list != range(65536):
            s_port = f"{rule_ports_list.start}:{rule_ports_list.stop - 1} "
        else:
            s_port = ""
    else:
        s_port = ",".join(map(str, rule_ports_list))
    return s_port


def _build_ports(rule_ports_list: Union[Iterable[int], range]) -> list[str]:
    """The ``--dports`` values of a rule: none for an empty port field, which matches no port, as in the Python
    layer; else lists of at most 15 ports, or a range ("" for every port)."""
    if isinstance(rule_ports_list, range):
        return [_build_port(rule_ports_list)]
    ports = list(rule_ports_list)
    return [_build_port(ports[i : i + _MULTIPORT_MAX]) for i in range(0, len(ports), _MULTIPORT_MAX)]


def _build_network(network_obj: Union[IPv4Network, IPv6Network], ipv6: bool, local: bool = False) -> str:
    """The address match of a rule, empty for any address.

    ``local`` is for an IN rule, whose network is the local address a socket binds: the wildcard address then
    stands for every local address.
    """
    network = ""
    any_address = ("0.0.0.0/0", "0.0.0.0/32") if local else ("0.0.0.0/0",)
    if not ipv6:
        if not isinstance(network_obj, IPv4Network):
            return ""
        if network_obj.compressed not in any_address:
            network = f"{network_obj.compressed} "
    else:
        if not isinstance(network_obj, IPv6Network):
            return ""
        if network_obj.compressed not in (("::/0", "::/128") if local else ("::/0",)):
            network = f"{network_obj.compressed} "
    return network


def rule_to_netfilter(socket_rules: SocketRules, dns_server: list[IPv4Address], is_ipv6: bool) -> List[str]:
    netfilter = [
        "*filter",
        ":INPUT DROP [0:0]",
        ":FORWARD DROP [0:0]",
        ":OUTPUT DROP [0:0]",
        "-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
        "-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
    ]
    for dns in dns_server:
        if (dns.version == 6) == is_ipv6:
            prefix = 128 if is_ipv6 else 32
            netfilter.append(f"-A OUTPUT -p udp -d {dns}/{prefix} --dport 53 -m conntrack --ctstate NEW -j ACCEPT")
    _map_direction = {Direction.IN: "INPUT", Direction.OUT: "OUTPUT"}
    _map_action = {Action.ALLOW: "ACCEPT", Action.DENY: "REJECT"}
    for (
        action,
        (rule_kind, network, rule_ports_list),
        rule_directions,
        _config,
    ) in socket_rules:
        for kind in rule_kind:
            # if is_ipv6 and isinstance(network_obj, ipaddress.IPv4Network):
            #     continue
            # elif not is_ipv6 and isinstance(network_obj, ipaddress.IPv6Network):
            #     continue
            for direction, ports in ((d, p) for d in rule_directions for p in _build_ports(rule_ports_list)):
                if is_ipv6 and isinstance(network, IPv6Network):
                    s_network = _build_network(network, is_ipv6, direction == Direction.IN)
                elif not is_ipv6 and isinstance(network, IPv4Network):
                    s_network = _build_network(network, is_ipv6, direction == Direction.IN)
                else:
                    continue

                # The network of an IN rule is the local address, as for bind() in the Python layer: the
                # destination of an incoming packet.
                s_network = f"-d {s_network}" if s_network else ""
                if direction == Direction.OUT:
                    s_state = "--ctstate NEW "
                else:
                    s_state = "--ctstate NEW,ESTABLISHED "

                if ports:
                    multiport = f"-m multiport --dports {ports} "
                else:
                    multiport = ""

                ip_rule: str
                if kind == Kind.TCP:
                    ip_rule = (
                        f"-A {_map_direction[direction]} "
                        f"-p tcp "
                        f"-m conntrack "
                        f"{s_state}"
                        f"{s_network}"
                        f"{multiport}"
                        f"-j {_map_action[action]}"
                    )
                elif kind == Kind.UDP:
                    ip_rule = (
                        f"-A {_map_direction[direction]} "
                        f"-p udp "
                        f"{s_network}"
                        f"{multiport}"
                        f"-j {_map_action[action]}"
                    )
                else:
                    assert "Internal error"
                    ip_rule = ""
                # assert ip_rule not in netfilter
                if ip_rule not in netfilter:
                    netfilter.append(ip_rule)

    netfilter.append("COMMIT")
    return netfilter
