# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Translation of the ``net=`` rules into an ``iptables-restore`` ruleset.

The Python layer judges a connection with ``guard_socket``. The providers that give the sandbox its own network
namespace (``unshare``, ``bwrap``, ``firejail``, ``qemu``) enforce the same rules a second time, in the kernel, so
that a native library or a child process cannot walk around the Python guard. This module only builds the text of
that ruleset; each provider loads it with ``iptables-restore`` inside the network namespace (or the guest) it
creates.

The ruleset is a ``*filter`` table made of:

1. A default policy of ``DROP`` on ``INPUT``, ``FORWARD`` and ``OUTPUT``: what no rule names is refused.
2. Two rules accepting the packets of connections already ``ESTABLISHED`` or ``RELATED``.
3. One rule per DNS server of the namespace, accepting new UDP packets to port 53 of that server only.
4. One rule per ``net=`` rule, per protocol, per direction and per group of ports, in the order of the profile.
   iptables stops at the first match, so the order of the ``net=`` lines keeps its meaning. ``ALLOW`` becomes
   ``ACCEPT`` and ``DENY`` becomes ``REJECT``, which answers at once instead of leaving the caller to time out.
5. ``COMMIT``.

Choices that follow the Python layer, so that both layers give the same answer:

- The network of an ``IN`` rule is the local address a socket binds, so it is matched as the destination of the
  incoming packet (``-d``). The wildcard address then stands for every local address.
- The network of an ``OUT`` rule is the destination of the packet (``-d``). An empty network matches any address.
- An empty port field matches no port. A range covering every port matches every port.
- ``OUT`` matches new connections only, ``IN`` also the established ones.
- A rule whose network is not of the IP version being built is skipped: the IPv4 and the IPv6 rulesets are built by
  two calls.

Limits:

- iptables matches addresses, not names: a host name is resolved beforehand, to the addresses the ruleset allows.
- The ``multiport`` match takes at most 15 ports, so a longer list becomes several rules.
- UDP rules do not use ``conntrack``: they match every datagram, not only the first of an exchange.
- Only ``tcp`` and ``udp`` exist; ``Unix`` sockets are not network traffic and are judged by the file rules.
"""

from ipaddress import IPv4Address, IPv4Network, IPv6Network
from typing import Iterable, List, Union

from ._contracts import ensure, post
from .guard_socket import Action, Direction, Kind, SocketRules

# The multiport match takes at most 15 ports.
_MULTIPORT_MAX = 15


@post(lambda result: isinstance(result, str))
@ensure(lambda rule_ports_list, result: rule_ports_list != range(65536) or result == "")
def _build_port(rule_ports_list: Union[Iterable[int], range]) -> str:
    if isinstance(rule_ports_list, range):
        if rule_ports_list != range(65536):
            s_port = f"{rule_ports_list.start}:{rule_ports_list.stop - 1} "
        else:
            s_port = ""
    else:
        s_port = ",".join(map(str, rule_ports_list))
    return s_port


@post(lambda result: all(len(ports.split(",")) <= _MULTIPORT_MAX for ports in result))
@ensure(
    lambda rule_ports_list, result: not isinstance(rule_ports_list, (list, tuple))
    or len(result) == -(-len(rule_ports_list) // _MULTIPORT_MAX)
)
@ensure(lambda rule_ports_list, result: not isinstance(rule_ports_list, range) or len(result) == 1)
def _build_ports(rule_ports_list: Union[Iterable[int], range]) -> list[str]:
    """The ``--dports`` values of a rule: none for an empty port field, which matches no port, as in the Python
    layer; else lists of at most 15 ports, or a range ("" for every port)."""
    if isinstance(rule_ports_list, range):
        return [_build_port(rule_ports_list)]
    ports = list(rule_ports_list)
    return [_build_port(ports[i : i + _MULTIPORT_MAX]) for i in range(0, len(ports), _MULTIPORT_MAX)]


@post(lambda result: result == "" or result.endswith(" "))
@ensure(lambda network_obj, ipv6, local=False, result="": ipv6 == isinstance(network_obj, IPv6Network) or result == "")
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


@post(lambda result: result[0] == "*filter" and result[-1] == "COMMIT" and result.count("COMMIT") == 1)
@post(lambda result: result[1:4] == [":INPUT DROP [0:0]", ":FORWARD DROP [0:0]", ":OUTPUT DROP [0:0]"])
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
                    continue  # pragma: no mutate

                # The network of an IN rule is the local address, as for bind() in the Python layer: the
                # destination of an incoming packet.
                s_network = f"-d {s_network}" if s_network else ""
                if direction == Direction.OUT:  # pragma: no mutate
                    s_state = "--ctstate NEW "
                else:
                    s_state = "--ctstate NEW,ESTABLISHED "

                if ports:
                    multiport = f"-m multiport --dports {ports} "
                else:
                    multiport = ""

                ip_rule: str
                if kind == Kind.TCP:  # pragma: no mutate
                    ip_rule = (
                        f"-A {_map_direction[direction]} "
                        f"-p tcp "
                        f"-m conntrack "
                        f"{s_state}"
                        f"{s_network}"
                        f"{multiport}"
                        f"-j {_map_action[action]}"
                    )
                elif kind == Kind.UDP:  # pragma: no mutate
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
