# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``smolvm machine run`` flags of the ``net=`` rules of a profile."""

import logging
from ipaddress import IPv4Network

from ..all_rules import AllRules
from ..guard_socket import Action, Direction, Kind

logger = logging.getLogger(__name__)

_ALL_PORTS = range(65536)


def _udp_ports(ports: tuple[int, ...] | range) -> list[str]:
    """The ``:PORT[-END]`` suffixes of an ``--allow-udp`` value: one empty suffix for every port."""
    if isinstance(ports, range):
        return [""] if ports == _ALL_PORTS else [f":{ports.start}-{ports.stop - 1}"]
    return [f":{port}" for port in ports]


def network_args(all_rules: AllRules) -> list[str]:
    """Return the flags that turn the guest network on, filtered by the rules; none leaves it off.

    ``--net`` alone filters nothing, so it is only emitted with an allow list. smolvm filters TCP by address and
    cannot express a port: such a rule opens every port of its address, which is reported.
    """
    allow_cidr: list[str] = []
    deny_cidr: list[str] = []
    allow_udp: list[str] = []
    for rule in all_rules.socket_rules:
        if Direction.OUT not in rule.directions:
            continue
        network = rule.mask.network
        if not isinstance(network, IPv4Network):
            logger.warning("smolvm cannot filter IPv6: %s is not enforced and stays closed", network)
            continue
        cidr = network.compressed
        ports = rule.mask.ports
        for kind in rule.mask.kinds:
            if kind == Kind.UDP and rule.action == Action.ALLOW:
                allow_udp += [cidr + suffix for suffix in _udp_ports(ports)]
            elif kind == Kind.TCP:
                if ports != _ALL_PORTS and rule.action == Action.ALLOW and network.prefixlen == 0:
                    logger.warning(
                        "smolvm cannot filter a TCP port: the port of %s is not enforced and stays closed, as opening "
                        "it would open every address",
                        cidr,
                    )
                    continue
                if ports != _ALL_PORTS:
                    logger.warning(
                        "smolvm cannot filter a TCP port: the port of %s is not enforced, every port is %s",
                        cidr,
                        "allowed" if rule.action == Action.ALLOW else "denied",
                    )
                (allow_cidr if rule.action == Action.ALLOW else deny_cidr).append(cidr)
    if not (allow_cidr or allow_udp):
        return []
    args = ["--net"]
    for flag, values in (("--allow-cidr", allow_cidr), ("--allow-udp", allow_udp), ("--deny-cidr", deny_cidr)):
        for value in dict.fromkeys(values):
            args += [flag, value]
    return args
