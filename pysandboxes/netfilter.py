# %%
import ipaddress
import socket
from typing import List

from .guard_socket import SocketRule, SPEC_TO_TYPE_MAP, SocketRules
from .types import ConfigLines

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
        if not isinstance(network_obj, ipaddress.IPv4Network):
            return ""
        if network_obj.compressed != '0.0.0.0/0':
            network = f'-d {network_obj.compressed} '
    else:
        if not isinstance(network_obj, ipaddress.IPv6Network):
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
        if not isinstance(network_obj, ipaddress.IPv4Network):
            return ""
        if network_obj.compressed != '0.0.0.0/0':
            network = f'-d {network_obj.compressed} '
    else:
        if not isinstance(network_obj, ipaddress.IPv6Network):
            return ""
        if network_obj.compressed != '::/0':
            network = f'-d {network_obj.compressed} '
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
    if is_ipv6:  # FIXME: why exclude not used?
        exclude = [socket.AF_INET, socket.IPPROTO_ICMP]
    else:
        exclude = [socket.AF_INET6, socket.IPPROTO_ICMPV6]
    for (action,
         (families, rule_types, network_obj, rule_ports_list),
         rule_direction_from_rule,_) in socket_rules:

        if not rule_types:
            rule_types = set(SPEC_TO_TYPE_MAP.values())
        for rule_type in rule_types:

            if is_ipv6 and isinstance(network_obj, ipaddress.IPv4Network):
                continue
            elif not is_ipv6 and isinstance(network_obj, ipaddress.IPv6Network):
                continue
            if rule_type in [socket.SOCK_STREAM]:
                if rule_direction_from_rule == "OUT":
                    s_ports = _build_port(rule_ports_list)
                    if s_ports:
                        multiport=f"-m multiport --dports {s_ports} "
                    else:
                        multiport=''
                    network = _build_network(network_obj, is_ipv6)
                    ip_rule = (
                            f"-A INPUT "
                            f"-p tcp "
                            f"{network}"
                            f"{multiport}"
                            f"-m conntrack --ctstate NEW,ESTABLISHED "
                            f"-j {_map_netfilter_action[action]} "
                    )
                    netfilter.append(ip_rule)
                else:
                    d_ports = _build_port(rule_ports_list)
                    if d_ports:
                        multiport=f"-m multiport --dports {d_ports} "
                    else:
                        multiport=''
                    network = _build_network(network_obj, is_ipv6)
                    ip_rule = (
                            f"-A INPUT "
                            f"-p tcp "
                            f"{network}"
                            f"{multiport}"
                            f"-m conntrack --ctstate NEW "
                            f"-j {_map_netfilter_action[action]} "
                    )
                    netfilter.append(ip_rule)
            elif rule_type in [socket.SOCK_DGRAM]:
                s_ports = _build_port(rule_ports_list)
                if rule_direction_from_rule == "IN":
                    sd="s"
                else:
                    sd="d"
                if s_ports:
                    multiport = f"-m multiport --{sd}ports {s_ports} "
                else:
                    multiport = ''
                ip_rule = (
                    f"-A {_map_netfilter_direction[rule_direction_from_rule]} "
                    f"-p udp "
                    f"{multiport}"
                    f"-j {_map_netfilter_action[action]} "
                )
                netfilter.append(ip_rule)
            elif rule_type in exclude:
                pass # Ignore
            else:
                assert False, "Unkown protocol"

    netfilter.append("COMMIT")
    return netfilter
