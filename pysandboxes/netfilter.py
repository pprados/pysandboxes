# %%
import socket
from ipaddress import IPv4Network, IPv4Address, IPv6Network, IPv6Address
from typing import List

from .guard_socket import SocketRules, Kind, Direction, Action

_map_netfilter_action = {"ALLOW": "ACCEPT", "DENY": "REJECT"}
_map_netfilter_direction = {"OUT": "OUTPUT", "IN": "INPUT"}
_map_netfilter_type = {
    socket.IPPROTO_TCP: "tcp",
    socket.IPPROTO_UDP: "udp",
    socket.IPPROTO_ICMP: "icmp",
    socket.IPPROTO_IPV6: "icmp",
    socket.IPPROTO_ICMPV6: "icmpv6",
    # -1: "any",  # 0 means "any
}


def _build_netfilter(rule_type,
                     network_obj, rule_direction_from_rule, rule_ports_list,
                     dest: str,
                     ipv6: bool = False) -> str:
    if rule_type in [socket.IPPROTO_ICMP, socket.IPPROTO_ICMPV6]:
        sdport = ''
    elif isinstance(rule_ports_list, range):
        if rule_ports_list != range(65535):
            sdport = f'-m multiport --{dest}ports {rule_ports_list.start}:{rule_ports_list.stop - 1} '
        else:
            sdport = ''
    else:
        sdport = f'-m multiport --{dest}ports ' + ','.join(
            map(str, rule_ports_list)) + ' '

    network = ''
    if not ipv6:
        if not isinstance(network_obj, IPv4Network):
            return ""
        if network_obj.compressed != '0.0.0.0/0':
            network = f'-d {network_obj.compressed} '
    else:
        if not isinstance(network_obj, IPv6Network):
            return ""
        if network_obj.compressed != '::/0':
            network = f'-d {network_obj.compressed} '
    if rule_type in [socket.IPPROTO_TCP]:
        if dest == "d":
            cstate = "-m conntrack --ctstate NEW,ESTABLISHED "
        else:
            cstate = "-m conntrack --ctstate ESTABLISHED "
    else:
        cstate = ""
    ip_rule = (
        f"{network}"
        f"{sdport}"
        f"{cstate}"
    )
    return ip_rule


def _build_port(rule_ports_list):
    if isinstance(rule_ports_list, range):
        if rule_ports_list != range(65535):
            s_port = f'{rule_ports_list.start}:{rule_ports_list.stop - 1} '
        else:
            s_port = None
    else:
        s_port = ','.join(map(str, rule_ports_list))
    return s_port


def _build_network(network_obj, ipv6: bool):
    network = ''
    if not ipv6:
        if not isinstance(network_obj, IPv4Network):
            return ""
        if network_obj.compressed != '0.0.0.0/0':
            network = f'{network_obj.compressed} '
    else:
        if not isinstance(network_obj, IPv6Network):
            return ""
        if network_obj.compressed != '::/0':
            network = f'{network_obj.compressed} '
    return network

def rule_to_netfilter(socket_rules: SocketRules,
                      is_ipv6: bool) -> List[str]:
    netfilter = [
        "*filter",
        ":INPUT DROP [0:0]",
        ":FORWARD DROP [0:0]",
        ":OUTPUT DROP [0:0]",
        "-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
        "-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
    ]
    _map_direction = {Direction.IN: "INPUT", Direction.OUT: "OUTPUT"}
    _map_action = {Action.ALLOW:"ACCEPT", Action.DENY:"REJECT"}
    for (action,
         (rule_kind, network, rule_ports_list),
         rule_directions,
         config) in socket_rules:

        for kind in rule_kind:

            # if is_ipv6 and isinstance(network_obj, ipaddress.IPv4Network):
            #     continue
            # elif not is_ipv6 and isinstance(network_obj, ipaddress.IPv6Network):
            #     continue
            for direction in rule_directions:
                ports = _build_port(rule_ports_list)
                if kind == Kind.TCP:
                    if is_ipv6 and isinstance(network,
                                              IPv6Network):
                        network = _build_network(network, is_ipv6)
                    elif not is_ipv6 and isinstance(network,IPv4Network):
                        network = _build_network(network, is_ipv6)
                    else:
                        continue

                    if direction == Direction.OUT:
                        s_state="--ctstate NEW "
                        s_ports="s"
                        s_network=f"-d {network} " if network else ""
                    else:
                        s_state="--ctstate NEW,ESTABLISHED "
                        s_ports = "d"
                        s_network = f"-s {network} " if network else ""

                    if ports:
                        multiport = f"-m multiport --{s_ports}ports {ports} "
                    else:
                        multiport = ''

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
                    # assert ip_rule not in netfilter
                    if ip_rule not in netfilter:
                        netfilter.append(ip_rule)

    netfilter.append("COMMIT")
    return netfilter
