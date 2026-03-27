# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Network access guard for PySandboxes.

This module implements network sandboxing by intercepting and controlling socket
operations. It patches the standard socket.socket class to enforce network access
rules defined in the configuration.

IMPORTANT: This module must be imported BEFORE any other modules that use the
standard socket library to ensure all socket operations are intercepted.

Security Model:
- Default-deny: All network connections are blocked by default
- Whitelist-based: Only explicitly allowed connections are permitted
- Rule-based filtering: Supports protocol, address, port, and direction filtering
- Learning mode: Can automatically generate rules based on observed behavior

Activation:
The patching happens automatically when this module is imported. Import order
is critical - this must occur before any modules that use sockets.

Limitations:
This is a Python-level protection that does NOT defend against:
- Native code network calls (C/C++ libraries)
- Child process network access
- Direct syscall usage
- Other IPC mechanisms

For complete protection, combine with OS-level sandboxing (firejail, containers).

Example:
    ```python
    import pysandboxes.guard_socket  # Must be first
    import requests  # Now protected
    import urllib.request  # Now protected
    ```
"""

import functools
import logging
import os
import socket
import sys
from enum import Enum, IntEnum
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)
from pathlib import Path
from typing import (
    Any,
    Callable,
    Generator,
    Iterator,
    NamedTuple,
    TypeAlias,
    cast,
)

from .e import RuleSocketConnectionRefusedError
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
from .main_logger import ErrorMsg, format_ruleref, pysandboxes_logger
from .sb_types import ConfigLine, ConfigLines

logger = logging.getLogger(__name__)

# Address format details can be found in the Python socket library documentation:
# https://docs.python.org/3/library/socket.html#address-families
Adresse_Type: TypeAlias = (
    str  # For AF_UNIX sockets
    | tuple[str, int]  # For AF_INET, AF_BLUETOOTH, AF_PACKET, AF_RDS sockets
    | tuple[str, int, int, int]  # For AF_INET6 sockets
    | tuple[int, bytes]  # For AF_NETLINK sockets
    | tuple[str]  # For AF_CAN, PF_SYSTEM sockets
    | tuple[str, str]  # For AF_ALG sockets
    | tuple[int, int]  # For AF_VSOCK, AF_QIPCRTR sockets
    | tuple[int, int, int, int, int]  # For AF_TIPC sockets
)

AddrInfoType = tuple[
    int,  # Family
    int,  # Type
    int,  # Proto
    str,  # cononame
    tuple[str, int]  # Ipv4 host,port
    | tuple[str, int, int, int],  # Ipv6 host, port, flowinfo, scopeid
]

InternalDNS = dict[str, list[AddrInfoType]]

PinDNS = ImmutableDict[str, tuple[AddrInfoType, ...]]


class Action(IntEnum):
    """Enumeration for socket connection actions."""

    DENY = 1  # Action to deny a connection
    ALLOW = 0  # Action to allow a connection


class Direction(IntEnum):
    """Enumeration for socket connection directions."""

    OUT = 1  # Direction for outgoing connections (e.g., client-side connect)
    IN = 0  # Direction for incoming connections (e.g., server-side bind)


class Kind(Enum):
    """Enumeration for socket types."""

    TCP = socket.SOCK_STREAM
    UDP = socket.SOCK_DGRAM
    UNKNOWN = socket.SOCK_DGRAM


# Parsed rule format used internally:
class SocketMask(NamedTuple):
    """Socket filtering criteria.

    Attributes:
        kinds: Allowed socket types (TCP, UDP).
        network: Network range to match against.
        ports: Allowed ports (tuple or range).
    """

    kinds: tuple[Kind, ...]
    network: IPv4Network | IPv6Network
    ports: tuple[int, ...] | range


class SocketRule(NamedTuple):
    """Socket access rule.

    Attributes:
        action: Action to take (ALLOW or DENY).
        mask: Filtering criteria for this rule.
        directions: Allowed directions (IN, OUT).
        config: Configuration line where rule was defined.
    """

    action: Action
    mask: SocketMask
    directions: tuple[Direction, ...]
    config: ConfigLine


SocketRules = tuple[SocketRule, ...]


class LearnSocketRule(NamedTuple):
    """Socket access observed during learning mode.

    Attributes:
        fn: Function name that made the socket call.
        kind: Socket type (TCP, UDP, UNKNOWN).
        address: Target address (hostname or IP).
        port: Target port number.
        direction: Connection direction (IN, OUT) or None.
        dns: Resolved IP addresses for hostname.
    """

    fn: str
    kind: Kind
    address: str
    port: int
    direction: Direction | None
    dns: tuple[IPv4Address | IPv6Address, ...]


_all_networks = ["0.0.0.0/0", "::1/0"]

_rules: SocketRules = cast(SocketRules, ())


def _yield_networks_from_string(
    input_str: str, pin_dns: InternalDNS
) -> Generator[IPv4Network | IPv6Network, None, None]:
    """Convert string to network objects.

    Args:
        input_str: Network specification (CIDR notation or hostname).

    Yields:
        Network objects for the input string.
    """
    host_dns, _ = _read_host_file()
    try:
        # Case 1: The input is a network in CIDR notation (e.g., '192.168.1.0/24')
        network = ip_network(input_str, strict=False)
        yield network
    except ValueError:
        # Case 2: The input is a hostname (e.g., 'www.google.com')
        # Resolve all IPs for the hostname and treat each as a /32 or /128 network
        if input_str in host_dns:
            # Use pined dns?
            for ip in host_dns[input_str]:
                pin_dns[input_str] = getaddrinfo(input_str, 0)
                yield ip_network(ip, strict=False)
        else:
            all_adresss = set()
            addr_info = cast(
                list[AddrInfoType], socket.getaddrinfo(host=input_str, port=0)
            )
            # Remove duplicate
            pin_dns[input_str] = addr_info
            for result in addr_info:
                address: str = result[4][0]
                all_adresss.add(ip_network(address))
            for addr in all_adresss:
                yield addr


def _parse_rule(
    rule: ConfigLine, errors: list[tuple[str, Path, int]], pin_dns: InternalDNS
) -> list[SocketRule] | None:
    """Parse a single network access rule.

    Args:
        rule: Configuration line containing net= rule.
        errors: List to collect parsing errors.

    Returns:
        List of parsed socket rules, or None if parsing failed.
    """
    if not rule.rule.startswith("net="):
        return []
    value_part = rule.rule[len("net=") :]
    rule_components = value_part.split("|", 4)  # Maxsplit is 4 for 5 parts
    if len(rule_components) != 5:
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"{rule.rule!r} has incorrect number of parts separated by '|'. "
                f"Expected 5, got {len(rule_components)}. "
                f"Format: "
                f"<{','.join([a.name for a in Action])}>|"
                f"<{','.join([k.name for k in Kind])} list or *>|"
                f"<ip/mask>, *|"
                f"<port list>|"
                f"<IN, OUT>.",
                rule.path,
                rule.ln,
            )
        )
        return None
    action, socket_specs_str, network_str, port_spec_str, directions = rule_components
    if action not in (Action.DENY.name, Action.ALLOW.name):
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"{rule.rule!r} "
                f"use an invalid action. Must be {Action.ALLOW.name!r} "
                f"or {Action.DENY.name!r}.",
                rule.path,
                rule.ln,
            )
        )

    # Parse SOCKET_SPECS
    parsed_rule_kinds: list[Kind] = []
    kind_input = [s.strip().lower() for s in socket_specs_str.split(",") if s.strip()]
    if not kind_input:
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"{rule.rule!r} "
                f"has empty socket specs.",
                rule.path,
                rule.ln,
            )
        )
    else:
        for spec_part in kind_input:
            spec_part = spec_part.upper()
            if spec_part in ["ANY", "*"]:
                if len(kind_input) > 1:
                    errors.append(
                        (
                            f"{format_ruleref(rule)}: "
                            f"In {rule.rule!r}, "
                            f"{spec_part!r} must be used alone, "
                            f"not combined with other specifiers.",
                            rule.path,
                            rule.ln,
                        )
                    )
                else:
                    parsed_rule_kinds = list(Kind)

            elif spec_part in [k.name for k in Kind]:
                parsed_rule_kinds.append(Kind[spec_part])
            else:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: "
                        f"{rule.rule!r} "
                        f"has unknown socket specifier {spec_part!r}. "
                        f"Valid specifiers: any, {', '.join([k.name for k in Kind])}.",
                        rule.path,
                        rule.ln,
                    )
                )

    if not isinstance(network_str, str) or not network_str.strip():
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"In {rule.rule!r}, "
                f"network part must be set.",
                rule.path,
                rule.ln,
            )
        )
    if not isinstance(port_spec_str, str):
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"In {rule.rule!r}, "
                f"port spec part is not valid.",
                rule.path,
                rule.ln,
            )
        )
    split_directions = directions.split(",")
    parser_directions: tuple[Direction, ...]
    if not set(split_directions).issubset({Direction.IN.name, Direction.OUT.name, "*"}):
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"In {rule.rule!r}, "
                f"direction is not {Direction.IN.name!r} "
                f"or {Direction.OUT.name!r}.",
                rule.path,
                rule.ln,
            )
        )
        parser_directions = tuple()
    else:
        if "*" in split_directions:
            parser_directions = tuple(Direction)
        else:
            parser_directions = tuple([Direction[d] for d in split_directions])

    ports_list_or_range: tuple[int, ...] | range = ()
    try:
        ports_list_or_range = _convert_ports_range(port_spec_str)
    except ValueError:
        errors.append(
            (
                f"{format_ruleref(rule)}: " f"In {rule.rule!r}, " f"invalid port list.",
                rule.path,
                rule.ln,
            )
        )
    if network_str in ("*",):
        networks = _all_networks
    else:
        networks = [network_str]

    if errors:
        return None

    def _for_each_networks() -> Iterator[SocketRule]:
        for network in networks:
            for net in _yield_networks_from_string(network, pin_dns):
                yield SocketRule(
                    Action[action],
                    SocketMask(
                        tuple(parsed_rule_kinds),
                        # May not be resolved
                        net,
                        ports_list_or_range,
                    ),
                    parser_directions,
                    config=rule,
                )

    try:
        r = list(_for_each_networks())
        return r
    except socket.gaierror:
        errors.append(
            (
                f"{format_ruleref(rule)}: "
                f"In {rule.rule!r}, "
                f"invalid network specification. "
                f"That does not resolve to any network.",
                rule.path,
                rule.ln,
            )
        )
        return None


def parse_rules(
    rules: ConfigLines, errors: list[ErrorMsg]
) -> tuple[SocketRules, ConfigLines, PinDNS]:
    """Parse network access rules from configuration.

    Args:
        rules: Configuration lines to parse.
        errors: List to collect parsing errors.

    Returns:
        Tuple of parsed socket rules and remaining config lines.
    """
    socket_rules = []
    ignore_rules = []
    dns: InternalDNS = {}
    for rule in rules:
        parsed_rules = _parse_rule(rule, errors, dns)
        if parsed_rules:
            socket_rules.extend(parsed_rules)
        elif parsed_rules is not None:
            ignore_rules.append(rule)

    # Remove duplicates and sort for consistency
    sorted_rules: list[SocketRule] = sorted(
        set(socket_rules),
        key=lambda r: (
            r.action,
            len(r.mask.kinds),
            len(r.mask.ports),
            len(r.directions),
        ),
        reverse=True,
    )
    pin_dns_raw = {k: tuple(v) for k, v in dns.items()}
    pin_dns = ImmutableDict(pin_dns_raw)
    return tuple(sorted_rules), ignore_rules, pin_dns


def _flatten_ports(input_ports: set[int | range]) -> set[int]:
    """Convert port ranges to individual port numbers.

    Args:
        input_ports: Set containing integers and ranges.

    Returns:
        Set of individual port numbers.
    """
    result: set[int] = set()
    for element in input_ports:
        if isinstance(element, int):
            result.add(element)
        elif isinstance(element, range):
            for p in element:
                result.add(p)
        else:
            assert False, f"Type not supported : {type(element)}"  # noqa: B011
    return result


def _convert_ports_range(syntax: str) -> tuple[int, ...] | range:
    """Convert port specification string to port numbers or range.

    Converts strings like "80,443,8000-8080,*" into port collections.

    Args:
        syntax: Port specification string.

    Returns:
        Tuple of port numbers or range object for '*'.

    Raises:
        ValueError: For invalid port syntax.
    """
    """
    Converts a port specification string (e.g., "80,443,8000-8080,*")
    into a sorted list of unique integer port numbers or a range object for '*'.

    Args:
        syntax: The port specification string.

    Returns:
        A sorted list of integers representing individual ports and expanded ranges,
        or a range(0, 65535) if '*' is specified. Returns an empty list for
        invalid syntax.
    """
    use_range = False
    max_port = 65535  # Maximum valid port number
    if not syntax:
        return tuple()
    if syntax.strip() == "*":
        return range(max_port + 1)  # Represents all ports
    ports: set[int | range] = set()
    elements = syntax.split(",")
    for element in elements:
        element = element.strip()
        if not element:
            continue
        if "-" in element:
            limits = element.split("-", 1)
            if len(limits) == 2:
                start_str, end_str = limits[0].strip(), limits[1].strip()
                if not start_str:
                    raise ValueError(
                        f"Invalid range format: {element!r}. "
                        f"Range _start cannot be empty."
                    )
                try:
                    start = int(start_str)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid _start port number {start_str!r} "
                        f"in range {element!r}."
                    ) from e
                if not (0 <= start <= max_port):
                    raise ValueError(
                        f"Start port {start} in range {element!r} is out of "
                        f"valid range (0-{max_port})."
                    )

                if end_str == "":  # Handles open-ended ranges like "8000-"
                    end = max_port
                else:
                    try:
                        end = int(end_str)
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid end port number {end_str!r} in range {element!r}."
                        ) from e
                    if not (0 <= end <= max_port):
                        raise ValueError(
                            f"End port {end} in range {element!r} is out of "
                            f"valid range (0-{max_port})."
                        )
                if start == end:
                    ports.add(start)
                elif start <= end:
                    if not use_range and not len(ports):
                        ports.add(range(start, end + 1))
                        use_range = True
                    else:
                        ports = cast(set[int | range], _flatten_ports(ports))
                        for p in range(start, end + 1):
                            ports.add(p)
                else:
                    raise ValueError(
                        f"Invalid range: _start port {start} is greater than "
                        f"end port {end} in {element!r}."
                    )
            else:
                raise ValueError(
                    f"Invalid range format: {element!r}. Unexpected hyphen usage."
                )
        else:
            try:
                port = int(element)
                if not (0 <= port <= max_port):
                    raise ValueError(
                        f"Port number {port} in {element!r} is out of "
                        f"valid range (0-{max_port})."
                    )
                ports.add(port)
            except ValueError as e:
                raise ValueError(f"Invalid port number {element!r}.") from e
    if len(ports) == 1:
        first = next(iter(ports))
        if isinstance(first, range):
            return first
    return tuple(sorted(cast(set[int], ports)))


@functools.lru_cache(maxsize=1000)
def getaddrinfo(
    host: str | bytes | None,
    port: bytes | str | int,
    family: int = 0,
    socktype: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> Any:
    """Cached DNS resolution for socket addresses.

    Args:
        host: Hostname to resolve.
        port: Port number (ignored in resolution).
        family: Address family filter.
        socktype: Socket type filter.
        proto: Protocol filter.
        flags: Additional resolution flags.

    Returns:
        List of address info tuples.
    """
    return socket.getaddrinfo(
        host=host, port=port, family=family, type=socktype, proto=proto, flags=flags
    )


def _check_address_with_rules(
    socket_rules: SocketRules,
    socket_kind: Kind,
    address: tuple[str, int],
    conn_direction: Direction,
) -> None:
    """Check if socket address is allowed by configured rules.

    Args:
        socket_rules: Active socket access rules.
        socket_kind: Type of socket (TCP, UDP).
        address: Target address (hostname/IP, port).
        conn_direction: Connection direction (IN or OUT).

    Raises:
        RuleSocketConnectionRefusedError: If access is denied by rules.
        ValueError: For invalid address or port values.
    """
    """
    Checks if a given address and port are allowed for the specified connection
    directions based on the configured rules and the derived implicit default policy.
    (Docstring needs update for new socket_instance_family, socket_instance_proto args)
    """
    # logger.debug(
    #     "_check_address_with_rules(address=%s, conn_direction=%s, kind=%s)",
    #     address, conn_direction.name, socket_kind.name)
    hostname, destination_port = address

    # TODO: cache?
    if not isinstance(destination_port, int) or not (0 <= destination_port <= 65535):
        raise ValueError(f"Invalid port number: {destination_port}")

    unique_ips: list[IPv4Address | IPv6Address]
    use_hostname = False
    try:
        unique_ips = [ip_address(hostname)]
    except ValueError:
        try:
            # Resolve hostname to IP addresses using the socket instance's family,
            # type, and proto
            infos = getaddrinfo(hostname, 0)
            use_hostname = True
        except socket.gaierror:
            # Fallback if the specific proto causes issues, try with
            # proto=0 (OS default for family/type)
            # This might happen if self.proto is something specific but
            # getaddrinfo needs a more general hint
            try:
                infos = getaddrinfo(hostname, 0, socktype=socket_kind.value, proto=0)
            except socket.gaierror as e:
                raise ValueError(
                    f"Invalid hostname or IP address (resolution failed): {hostname}"
                ) from e
        # %% Analyse ips
        ip_objects = []
        for _, _, _, _, sockaddr in infos:
            # sockaddr[0] is the IP address string
            addr_str = sockaddr[0]
            ip_objects.append(ip_address(addr_str))

        unique_ips = list(dict.fromkeys(ip_objects))
    if not unique_ips:
        raise ValueError(
            f"Invalid hostname or IP address (resolution failed): {hostname}"
        )

    # %% Analyse rules
    for rule_type_to_check in (Action.DENY, Action.ALLOW):
        for ip_host in unique_ips:
            for (
                action,
                (rule_kind, network_list, rule_ports_list),
                rule_directions,
                config,
            ) in socket_rules:
                if action == rule_type_to_check:
                    kind_match = (rule_kind != Kind.UNKNOWN) or (
                        socket_kind in rule_kind
                    )

                    if kind_match:
                        if conn_direction in rule_directions:
                            if (
                                ip_host in network_list
                                and destination_port in rule_ports_list
                            ):
                                if action == Action.DENY:
                                    if use_hostname:
                                        pysandboxes_logger.error(
                                            "Connection to '%s' (%s:%s) "
                                            "DENIED by explicit rule "
                                            "'%s' from %s",
                                            hostname,
                                            ip_host,
                                            destination_port,
                                            config.rule,
                                            format_ruleref(config),
                                        )
                                        raise RuleSocketConnectionRefusedError(
                                            f"Guard network connection to "
                                            f"{hostname!r} "
                                            f"({ip_host}:{destination_port}) "
                                            f"{action} by rule "
                                            f"{config.rule!r} "
                                            f"from {format_ruleref(config)})."
                                        )
                                    else:
                                        pysandboxes_logger.error(
                                            "Connection to [%s]:%s "
                                            "DENIED by explicit rule "
                                            "'%s' from %s",
                                            ip_host,
                                            destination_port,
                                            config.rule,
                                            format_ruleref(config),
                                        )
                                        raise RuleSocketConnectionRefusedError(
                                            f"Guard network connection to "
                                            f"[{ip_host}]:{destination_port} "
                                            f"{action} by rule "
                                            f"{config.rule!r} "
                                            f"from {format_ruleref(config)})."
                                        )

                                elif action == Action.ALLOW:
                                    if pysandboxes_logger.isEnabledFor(logging.DEBUG):
                                        if use_hostname:
                                            pysandboxes_logger.debug(
                                                "Connection to '%s' ([%s]:%s) "
                                                "ALLOW by explicit rule "
                                                "'%s' from %s",
                                                hostname,
                                                ip_host,
                                                destination_port,
                                                config.rule,
                                                format_ruleref(config),
                                            )
                                        else:
                                            pysandboxes_logger.debug(
                                                "Connection to [%s]:%s "
                                                "ALLOW by explicit rule "
                                                "'%s' from %s",
                                                ip_host,
                                                destination_port,
                                                config.rule,
                                                format_ruleref(config),
                                            )
                                    return
    try:
        ip_address(hostname)
        target = f"[{hostname}]:{destination_port}"
    except ValueError:
        target = (
            f"'[{hostname}]:{destination_port}' "
            f"({', '.join([str(unique_ip) for unique_ip in unique_ips])}:{destination_port}) "
        )

    pysandboxes_logger.error(
        "Connection to '%s' " "DENIED by implicit default policy.", target
    )
    raise RuleSocketConnectionRefusedError(
        f"Guard network connection to {str(target)!r} "
        f"DENIED by implicit default policy."
    )


# see _scoket.pyi
# ReadableBuffer type for socket operations
# Using Any to avoid Buffer import issues with pyright
ReadableBuffer: TypeAlias = Any
_Address: TypeAlias = tuple[Any, ...] | str | Any
_RetAddress: TypeAlias = Any

_pin_dns: ImmutableDict[str, tuple[AddrInfoType, ...]] = ImmutableDict({})


def set_pin_dns(dns: ImmutableDict[str, tuple[AddrInfoType, ...]]) -> None:
    global _pin_dns
    assert not _pin_dns
    logger.debug(
        "pin_dns=\n  "
        + "\n  ".join(
            f"[{k}]:  " + ", ".join({x[4][0] for x in v}) for k, v in dns.items()
        )
    )
    _pin_dns = dns


# Not used
def _get_family(ip: str) -> int:
    ip_object = ip_address(ip)
    if ip_object.version == 4:
        family = socket.AF_INET
    elif ip_object.version == 6:
        family = socket.AF_INET6
    else:
        family = 0
    return family


# %%
def _wrap_socket_gethostbyname(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(name: str, *args: Any, **kwargs: dict[str, Any]) -> Any:
        if isinstance(name, str) and name in _pin_dns:
            for addr_info in _pin_dns[name]:
                if addr_info[0] == socket.AF_INET:
                    return addr_info[4][0]
            err = socket.gaierror()
            err.errno = 3
            err.strerror = "Temporary failure in name resolution"
            raise err
        result = func(name, *args, **kwargs)
        if isinstance(name, str) and name and is_learning_mode():
            add_learning_rule(
                LearnSocketRule(
                    "gethostbyname",
                    Kind.UNKNOWN,
                    name,
                    0,
                    Direction.OUT,
                    (ip_address(result),),
                )
            )
        return result

    return wrapper


def _wrap_socket_gethostbyname_ex(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(name: str, *args: Any, **kwargs: dict[str, Any]) -> Any:
        result = func(name, *args, **kwargs)
        if isinstance(name, str) and name in _pin_dns:
            addr_info = _pin_dns[name]
            can_name = addr_info[0][3] or name
            return (
                can_name,
                [],
                [
                    dns_conf[4][0]
                    for dns_conf in _pin_dns[name]
                    if dns_conf[0] == socket.AF_INET
                ],
            )
        if isinstance(name, str) and name and is_learning_mode():
            add_learning_rule(
                LearnSocketRule(
                    "gethostbyname_ex",
                    Kind.UNKNOWN,
                    name,
                    0,
                    Direction.OUT,
                    tuple([ip_address(r) for r in result[2]]),
                )
            )
        return result

    return wrapper


def _wrap_socket_getaddrinfo(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        host: bytes | str | None,
        port: bytes | str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> list[AddrInfoType]:
        if isinstance(host, bytes):
            host = host.decode("utf-8")
        result: list[AddrInfoType]
        if isinstance(host, str) and host in _pin_dns:
            result = list(cast(tuple[AddrInfoType], _pin_dns[host]))

            # Filter results based on family, type, proto, and flags.
            if family != 0:
                result = [r for r in result if r[0] == family]
            if type != 0:
                result = [r for r in result if r[1] == type]
            if proto != 0:
                result = [r for r in result if r[2] == proto]

            # Patch port
            def _patch_port(new_port: int, addr: AddrInfoType) -> AddrInfoType:
                address = list(addr[4])
                address[1] = new_port
                return addr[0], addr[1], addr[2], addr[3], cast(Any, tuple(address))

            if port is not None:
                result = list(_patch_port(int(port), dns_conf) for dns_conf in result)
        else:
            result = func(host, port, family, type, proto, flags, *args, **kwargs)
        if isinstance(host, str) and host and is_learning_mode():
            add_learning_rule(
                LearnSocketRule(
                    "getaddrinfo",
                    Kind.UNKNOWN,
                    host,
                    int(port) if port is not None else 0,
                    Direction.OUT,
                    tuple({ip_address(info[4][0]) for info in result}),
                )
            )
        return result

    return wrapper


def _check_address(
    self: Any, address: tuple[str, int], conn_direction: Direction
) -> None:
    _check_address_with_rules(_rules, Kind(self.type), address, conn_direction)


def _socket_add_learning_rule(
    self: Any,
    address: tuple[str, int],
    conn_direction: Direction,
    rule: LearnSocketRule,
) -> None:
    try:
        _check_address(
            self,
            address,
            conn_direction,
        )
    except RuleSocketConnectionRefusedError:
        add_learning_rule(rule)


def _wrap_socket_bind(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Any, address: Adresse_Type) -> None:
        if (
            isinstance(address, tuple)
            and len(address) >= 2
            and isinstance(address[0], str)
            and isinstance(address[1], int)
        ):
            if is_learning_mode():
                _socket_add_learning_rule(
                    self,
                    (str(address[0]), int(address[1])),
                    Direction.IN,
                    LearnSocketRule(
                        "bind",
                        Kind(self.type),
                        address[0],
                        int(address[1]),
                        Direction.IN,
                        (),  # pin_dns
                    ),
                )
            else:
                _check_address(
                    self,
                    (str(address[0]), int(address[1])),
                    conn_direction=Direction.IN,
                )
        elif isinstance(address, str):  # AF_UNIX
            logger.debug(
                "Allowing bind to AF_UNIX address (not subject to IP rules): %s",
                address,
            )
        else:
            logger.warning(
                "Unexpected address format for bind: %s. Skipping IP rule check.",
                address,
            )
        func(self, address)

    return wrapper


def _wrap_socket_connect(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Any, address: Adresse_Type) -> None:
        if (
            isinstance(address, tuple)
            and len(address) >= 2
            and isinstance(address[0], str)
            and isinstance(address[1], int)
        ):
            if is_learning_mode():
                _socket_add_learning_rule(
                    self,
                    (str(address[0]), int(address[1])),
                    Direction.OUT,
                    LearnSocketRule(
                        "connect",
                        Kind(self.type),
                        address[0],
                        int(address[1]),
                        Direction.OUT,
                        (),  # pin_dns
                    ),
                )
            else:
                _check_address(
                    self,
                    (str(address[0]), int(address[1])),
                    conn_direction=Direction.OUT,
                )
        elif isinstance(address, str):  # AF_UNIX
            logger.debug(
                "Allowing connect to AF_UNIX address (not subject to IP rules): %s",
                address,
            )
        else:
            logger.warning(
                "Unexpected address format for connect: %s. Skipping IP rule check.",
                address,
            )
            assert False, (  # noqa: B011
                f"Unexpected address format for connect: "
                f"{address}. Skipping IP rule check."
            )
        return func(self, address)

    return wrapper


def _wrap_socket_connect_ex(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Any, address: Adresse_Type) -> int:
        if (
            isinstance(address, tuple)
            and len(address) >= 2
            and isinstance(address[0], str)
            and isinstance(address[1], int)
        ):
            if is_learning_mode():
                _socket_add_learning_rule(
                    self,
                    (str(address[0]), int(address[1])),
                    Direction.OUT,
                    LearnSocketRule(
                        "connect_ex",
                        Kind(self.type),
                        address[0],
                        int(address[1]),
                        Direction.OUT,
                        (),  # pin_dns
                    ),
                )
            else:
                self._check_address(
                    self,
                    (str(address[0]), int(address[1])),
                    conn_direction=Direction.OUT,
                )
        elif isinstance(address, str):  # AF_UNIX
            logger.debug(
                "Allowing connect_ex to AF_UNIX address (not subject to IP rules): %s",
                address,
            )
        else:
            logger.warning(
                "Unexpected address format for connect_ex: %s. Skipping IP rule check.",
                address,
            )
        return func(self, address)

    return wrapper


def _wrap_socket_sendto(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Any, data: ReadableBuffer, address: _Address, /) -> int:
        if (
            isinstance(address, tuple)
            and len(address) >= 2
            and isinstance(address[0], str)
            and isinstance(address[1], int)
        ):
            if self.type == Kind.UDP.value:
                if is_learning_mode():
                    _socket_add_learning_rule(
                        self,
                        (str(address[0]), int(address[1])),
                        Direction.OUT,
                        LearnSocketRule(
                            "sendto",
                            Kind(self.type),
                            address[0],
                            int(address[1]),
                            Direction.OUT,
                            (),  # pin_dns
                        ),
                    )
                else:
                    _check_address(
                        self,
                        (str(address[0]), int(address[1])),
                        conn_direction=Direction.OUT,
                    )
            else:
                logger.debug("Invalid usage of sendto")
        return func(self, data, address)

    return wrapper


def patch_rules(learn: bool) -> dict[str, Callable]:
    """Provide socket patching rules for guard activation.

    Returns:
        Dictionary of socket module patches.
    """
    rules = {
        "socket.socket.bind": _wrap_socket_bind,
        "socket.socket.connect": _wrap_socket_connect,
        "socket.socket.connect_ex": _wrap_socket_connect_ex,
        "socket.socket.sendto": _wrap_socket_sendto,
        "socket.gethostbyname": _wrap_socket_gethostbyname,
        "socket.gethostbyname_ex": _wrap_socket_gethostbyname_ex,
        "socket.getaddrinfo": _wrap_socket_getaddrinfo,
    }
    return rules


def activate_guard(rules: SocketRules) -> None:
    """Activate socket guard with specified rules.

    Args:
        rules: Socket access rules to enforce.

    Raises:
        RuntimeError: If guard is already activated.
    """
    if not rules:
        return
    global _rules
    if _rules:
        raise RuntimeError("Guard_socket already activated.")
    _rules = rules


def _read_host_file() -> tuple[
    dict[str, set[IPv4Address | IPv6Address]],
    dict[IPv4Address | IPv6Address, set[str]],
]:
    dns: dict[str, set[IPv4Address | IPv6Address]] = {}
    inverse_dns: dict[IPv4Address | IPv6Address, set[str]] = {}
    # Read the host file
    # Détecter le système d'exploitation pour trouver le bon chemin
    if sys.platform == "win32":
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            system_root = r"C:\Windows"
        hosts_file = Path(system_root) / r"System32\drivers\etc\hosts"
    elif (
        sys.platform.startswith("linux")
        or sys.platform == "darwin"
        or sys.platform.startswith("freebsd")
        or sys.platform == "sunos"
    ):
        hosts_file = Path("/etc/hosts")
    else:
        return {}, {}
    if hosts_file.exists() and hosts_file.is_file() and os.access(hosts_file, os.R_OK):
        host_lines = hosts_file.read_text().split("\n")
        for line in host_lines:
            if line.startswith("#"):
                continue
            line = line.strip()
            if line:
                ip, *hosts = line.split()
                if hosts:
                    inverse_dns.setdefault(ip_address(ip), set()).add(hosts[0])
                for host in hosts:
                    dns.setdefault(host, set()).add(ip_address(ip))
    # Force localhost
    return dns, inverse_dns


def generate_rules(
    learn: set[Any],
) -> list[str]:
    """Generate socket rules from learning data.

    Creates network access rules based on observed socket connections
    during learning mode execution.

    Args:
        learn: Set of learned socket access patterns.

    Returns:
        List of net= configuration rule strings.
    """
    result = set()
    dns, inverse_dns = _read_host_file()

    # 1. Get pin_dns info
    for learn_rule in filter(lambda x: isinstance(x, LearnSocketRule), learn):
        if learn_rule.fn in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
            for ip in learn_rule.dns:
                inverse_dns.setdefault(ip, set()).add(learn_rule.address)
                dns.setdefault(learn_rule.address, set()).add(ip)

    # 2. Map access to pin_dns
    by_destination: dict[tuple[str, Kind], tuple[list, list]] = {}
    for learn_rule in filter(lambda x: isinstance(x, LearnSocketRule), learn):
        if learn_rule.fn not in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
            if learn_rule.address in dns:
                # Find ip in DNS
                destinations = {learn_rule.address}
            else:
                # Direct IP access
                ip = ip_address(learn_rule.address)
                if ip in inverse_dns:
                    # but it's match a domain
                    destinations = inverse_dns[ip]
                else:
                    # Else, use mask
                    if ip.version == 4:
                        mask = 32
                    elif ip.version == 6:
                        mask = 128
                    else:
                        mask = 0  # Unknown mask
                    if mask:
                        destinations = {f"{learn_rule.address}/{mask}"}
                    else:
                        destinations = {str(learn_rule.address)}
            for destination in destinations:
                # Search alias in env
                for k, v in os.environ.items():
                    if v == destination:
                        destination = f"${{{k}}}"
                in_out = by_destination.get((destination, learn_rule.kind), ([], []))
                if learn_rule.direction is Direction.IN:
                    in_out[0].append(learn_rule)
                else:
                    in_out[1].append(learn_rule)
                by_destination[(destination, learn_rule.kind)] = in_out

    # 3. Generate rules

    # Try to find port alias
    key_for_port = {}
    for k, v in os.environ.items():
        if "port" in k.lower():
            try:
                # Look like a port?
                int(v)
                key_for_port[int(v)] = f"${{{k}}}"
            except ValueError:
                pass  # Ignore
    for (destination, kind), (
        in_rules_for_dest,
        out_rules_for_dest,
    ) in by_destination.items():
        # Aggregate ports
        if in_rules_for_dest:
            in_ports = {
                key_for_port.get(rule.port, str(rule.port))
                for rule in in_rules_for_dest
            }  # Can not be a range
            rule_str = (
                f"net=ALLOW|{kind.name}|"
                f"{'*' if destination == '0.0.0.0' else destination}|"
                f"{','.join(in_ports)}|"
                f"{Direction.IN.name}"
            )
            # Check if this rules is already present
            for rule in _rules:
                if rule.config.rule == rule_str:
                    break  # Ignore rule
            else:
                result.add(rule_str)
        if out_rules_for_dest:
            out_ports = {
                key_for_port.get(rule.port, str(rule.port))
                for rule in out_rules_for_dest
            }  # Can not be a range
            rule_str = (
                f"net=ALLOW|{kind.name}|"
                f"{destination}|"
                f"{','.join(out_ports)}|"
                f"{Direction.OUT.name}"
            )
            result.add(rule_str)
    return sorted(list(result))


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_sockets() -> None:
        global _rules
        _rules = ()
