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
import threading
import time
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
    Iterable,
    Iterator,
    NamedTuple,
    TypeAlias,
    cast,
)

from .e import RuleSocketConnectionRefusedError
from .guard_files import _apply_dest_to_src_rules
from .guard_wraps import guard_wraps
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
    tuple[str, int] | tuple[str, int, int, int],  # Ipv4 host,port  # Ipv6 host, port, flowinfo, scopeid
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
    # Deliberately the same value as UDP, so it stays an alias rather than a
    # third member: ``list(Kind)`` builds the vocabulary a net= rule accepts
    # (see _parse_kinds and the error messages), and "UNKNOWN" is not a
    # specifier a profile may write. It only names the absent socket type when
    # a learning record comes from a DNS lookup instead of a socket.
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
# An empty rule set is a legitimate deny-all whitelist, so it cannot double as
# "no rules loaded": the two states must be told apart by their own flag. False
# means the guard lets everything through, and only the pytest-only disarm below
# ever returns it to False -- production loads once and keeps them.
#
# This flag belongs to the *install* phase, not to the *arm* phase owned by
# lifecycle: this guard enforces as soon as its rules are loaded, whereas
# guard_api waits for user code. Naming both "_armed" made two different phases
# look like one.
_rules_loaded: bool = False


# Loopback names resolvable only through /etc/hosts. That file is not
# guaranteed to carry them: Docker Desktop rewrites it without the
# standard IPv6 block, and minimal images ship none of the entries.
# An unresolvable name in a net= rule is a fatal config error, so a
# profile written against these names would be valid or not depending
# on the host. Only names absent from the file get the fallback, so a
# correct /etc/hosts still wins. "localhost" maps to IPv4 alone, as
# the standard file does: adding ::1 would silently widen a rule.
_LOOPBACK_HOSTS: dict[str, tuple[str, ...]] = {
    "localhost": ("127.0.0.1",),
    "ip6-localhost": ("::1",),
    "ip6-loopback": ("::1",),
}


def _addr_infos_from_ips(ips: Iterable[IPv4Address | IPv6Address]) -> list[AddrInfoType]:
    """Build addrinfo entries for known IPs, without asking a resolver.

    Both socket types are emitted: the patched getaddrinfo filters
    pinned entries by type, so a stream-only answer would leave an UDP
    lookup with nothing.
    """
    infos: list[AddrInfoType] = []
    for ip in sorted(ips, key=str):
        family: int
        sockaddr: tuple[str, int] | tuple[str, int, int, int]
        if ip.version == 6:
            family, sockaddr = socket.AF_INET6, (str(ip), 0, 0, 0)
        else:
            family, sockaddr = socket.AF_INET, (str(ip), 0)
        for kind, proto in (
            (socket.SOCK_STREAM, socket.IPPROTO_TCP),
            (socket.SOCK_DGRAM, socket.IPPROTO_UDP),
        ):
            infos.append((family, kind, proto, "", cast(Any, sockaddr)))
    return infos


def _typed_addr_infos(infos: Iterable[AddrInfoType]) -> list[AddrInfoType]:
    """Split each untyped resolver entry into its stream and datagram forms.

    Windows answers an untyped lookup with type 0 and proto 0, one entry per address,
    where Linux gives one entry per type: pinned as is, the type filter of the patched
    getaddrinfo dropped every Windows entry.
    """
    typed: list[AddrInfoType] = []
    for family, kind, proto, canonname, sockaddr in infos:
        if kind:
            typed.append((family, kind, proto, canonname, sockaddr))
        else:
            typed.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, canonname, sockaddr))
            typed.append((family, socket.SOCK_DGRAM, socket.IPPROTO_UDP, canonname, sockaddr))
    return typed


_TRANSIENT_GAI_ERRNOS = frozenset(
    code
    for code in (
        getattr(socket, "EAI_AGAIN", None),
        getattr(socket, "EAI_SYSTEM", None),
    )
    if code is not None
)

_RESOLVE_RETRY_DELAYS = (0.2, 0.4)


def _is_transient_gai_error(error: socket.gaierror) -> bool:
    """Whether a resolution failure is worth retrying while parsing a configuration.

    A name that does not exist (`EAI_NONAME`, `EAI_FAIL`, `EAI_NODATA`) is the rule
    author's mistake and must surface at once. A resolver momentarily unreachable --
    one still starting up in a container, or answering under load -- reports
    `EAI_AGAIN` or `EAI_SYSTEM`, and the same name resolves a fraction of a second
    later. An error carrying no errno is treated as a real fault: better to surface
    it than to retry blindly.
    """
    return error.errno in _TRANSIENT_GAI_ERRNOS


def _resolve_with_retry(host: str) -> list[AddrInfoType]:
    """Resolve a hostname for a `net=` rule, retrying a transient resolver failure.

    `net=` rules are resolved when the configuration is parsed, so a resolver hiccup
    at startup would otherwise become a `ConfigSyntaxError` about an invalid network
    specification. The budget is deliberately small: parsing must not hang waiting
    for a resolver that is down.
    """
    for delay in _RESOLVE_RETRY_DELAYS:
        try:
            return cast(list[AddrInfoType], socket.getaddrinfo(host=host, port=0))
        except socket.gaierror as e:
            if not _is_transient_gai_error(e):
                raise
            pysandboxes_logger.debug("Transient DNS failure for %r (%s), retrying in %ss.", host, e, delay)
            time.sleep(delay)
    return cast(list[AddrInfoType], socket.getaddrinfo(host=host, port=0))


def _yield_networks_from_string(
    input_str: str, pin_dns: InternalDNS
) -> Generator[IPv4Network | IPv6Network, None, None]:
    """Convert string to network objects.

    Args:
        input_str: Network specification (CIDR notation or hostname).
        pin_dns: Resolution cache, filled in as names are resolved so a later
            lookup cannot be answered with a different address.

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
            try:
                pin_dns[input_str] = _typed_addr_infos(getaddrinfo(input_str, 0))
            except socket.gaierror:
                # The name is known here but not to the resolver: pin
                # the addresses the hosts table already gave us.
                pin_dns[input_str] = _addr_infos_from_ips(host_dns[input_str])
            for ip in host_dns[input_str]:
                yield ip_network(ip, strict=False)
        else:
            all_adresss = set()
            addr_info = _resolve_with_retry(input_str)
            # Remove duplicate
            pin_dns[input_str] = _typed_addr_infos(addr_info)
            for result in addr_info:
                address: str = result[4][0]
                all_adresss.add(ip_network(address))
            for addr in all_adresss:
                yield addr


def _parse_rule(rule: ConfigLine, errors: list[tuple[str, Path, int]], pin_dns: InternalDNS) -> list[SocketRule] | None:
    """Parse a single network access rule.

    Args:
        rule: Configuration line containing net= rule.
        errors: List to collect parsing errors.
        pin_dns: Resolution cache, filled in while the rule's host names are
            resolved so a later lookup cannot be answered with a different
            address.

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
                f"{format_ruleref(rule)}: " f"{rule.rule!r} " f"has empty socket specs.",
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
                f"{format_ruleref(rule)}: " f"In {rule.rule!r}, " f"network part must be set.",
                rule.path,
                rule.ln,
            )
        )
    if not isinstance(port_spec_str, str):
        errors.append(
            (
                f"{format_ruleref(rule)}: " f"In {rule.rule!r}, " f"port spec part is not valid.",
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
    except socket.gaierror as e:
        if _is_transient_gai_error(e):
            # The retries are exhausted. The rule may well be correct: say so, so
            # the reader looks at the resolver and not at the profile.
            reason = f"the name resolution failed temporarily ({e}). Check the resolver, not the rule."
        else:
            reason = "invalid network specification. That does not resolve to any network."
        if action == Action.ALLOW.name:
            # An ALLOW grants, so a name that resolves to nothing grants nothing:
            # dropping the rule leaves the implicit default policy in charge and a
            # host with no resolver still starts. A DENY is the mirror image --
            # dropping one lifts a restriction its author wrote on purpose -- so it
            # stays fatal, which refuses to start rather than run unrestricted.
            pysandboxes_logger.warning(
                "%s: In %r, %s Rule ignored: it allows nothing.",
                format_ruleref(rule),
                rule.rule,
                reason,
            )
            return []
        errors.append((f"{format_ruleref(rule)}: In {rule.rule!r}, {reason}", rule.path, rule.ln))
        return None


def parse_rules(rules: ConfigLines, errors: list[ErrorMsg]) -> tuple[SocketRules, ConfigLines, PinDNS]:
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
        elif parsed_rules is not None and not rule.rule.startswith("net="):
            # An empty result means two different things. From a line this guard
            # does not own it means "not mine", and the line goes on to the next
            # parser -- reaching the end unclaimed is what makes it an invalid
            # rule. From a net= line it means the rule was understood and yielded
            # no network, which is a rule that matches nothing, not an unknown
            # directive: claim it here or a tolerated ALLOW is reported as a
            # syntax error instead of being ignored.
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
                    raise ValueError(f"Invalid range format: {element!r}. " f"Range _start cannot be empty.")
                try:
                    start = int(start_str)
                except ValueError as e:
                    raise ValueError(f"Invalid _start port number {start_str!r} " f"in range {element!r}.") from e
                if not (0 <= start <= max_port):
                    raise ValueError(
                        f"Start port {start} in range {element!r} is out of " f"valid range (0-{max_port})."
                    )

                if end_str == "":  # Handles open-ended ranges like "8000-"
                    end = max_port
                else:
                    try:
                        end = int(end_str)
                    except ValueError as e:
                        raise ValueError(f"Invalid end port number {end_str!r} in range {element!r}.") from e
                    if not (0 <= end <= max_port):
                        raise ValueError(
                            f"End port {end} in range {element!r} is out of " f"valid range (0-{max_port})."
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
                        f"Invalid range: _start port {start} is greater than " f"end port {end} in {element!r}."
                    )
            else:
                raise ValueError(f"Invalid range format: {element!r}. Unexpected hyphen usage.")
        else:
            try:
                port = int(element)
                if not (0 <= port <= max_port):
                    raise ValueError(f"Port number {port} in {element!r} is out of " f"valid range (0-{max_port}).")
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
    return socket.getaddrinfo(host=host, port=port, family=family, type=socktype, proto=proto, flags=flags)


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
                raise ValueError(f"Invalid hostname or IP address (resolution failed): {hostname}") from e
        # %% Analyse ips
        ip_objects = []
        for _, _, _, _, sockaddr in infos:
            # sockaddr[0] is the IP address string
            addr_str = sockaddr[0]
            ip_objects.append(ip_address(addr_str))

        unique_ips = list(dict.fromkeys(ip_objects))
    if not unique_ips:
        raise ValueError(f"Invalid hostname or IP address (resolution failed): {hostname}")

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
                    # rule_kind is SocketMask.kinds, a tuple: comparing it to a
                    # Kind member was always true, so kind_match was always true
                    # and the socket type of a net= rule was never enforced --
                    # an ALLOW|TCP rule also let UDP through.
                    kind_match = socket_kind in rule_kind

                    if kind_match:
                        if conn_direction in rule_directions:
                            if ip_host in network_list and destination_port in rule_ports_list:
                                if action == Action.DENY:
                                    if use_hostname:
                                        pysandboxes_logger.error(
                                            "Connection to '%s' (%s:%s) " "DENIED by explicit rule " "'%s' from %s",
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
                                            "Connection to [%s]:%s " "DENIED by explicit rule " "'%s' from %s",
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
                                                "Connection to [%s]:%s " "ALLOW by explicit rule " "'%s' from %s",
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

    pysandboxes_logger.error("Connection to '%s' " "DENIED by implicit default policy.", target)
    raise RuleSocketConnectionRefusedError(
        f"Guard network connection to {str(target)!r} " f"DENIED by implicit default policy."
    )


def _check_unix_socket(address: str, *, write: bool, operation: str) -> None:
    """Authorize an AF_UNIX address against the file rules.

    ``net=`` rules describe IP endpoints only (``proto|host|port|direction``),
    so a Unix domain socket cannot be expressed by one. A socket path is a
    filesystem object, so authorization is delegated to the ``expose-ro=`` /
    ``expose-rw=`` rules: reaching it requires a rule covering that path.
    Without this, ``/var/run/docker.sock`` (root-equivalent on the host),
    the ssh-agent socket and the D-Bus socket are reachable unrestricted.

    Args:
        address: Filesystem path of the socket.
        write: Whether the operation needs write access to the path.
        operation: Socket operation name, for the error message.

    Raises:
        RuleSocketConnectionRefusedError: If no file rule covers the path.
    """
    remapped, rule = _apply_dest_to_src_rules(address, write=write)
    if rule or not remapped:
        pysandboxes_logger.error(
            "%s to AF_UNIX socket '%s' DENIED by implicit default policy.",
            operation,
            address,
        )
        raise RuleSocketConnectionRefusedError(
            f"Guard {operation} to AF_UNIX socket {address!r} DENIED: no "
            f"expose-ro=/expose-rw= rule covers this path."
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
    entries = (f"[{k}]:  " + ", ".join(x[4][0] for x in (v or ())) for k, v in dns.items())
    logger.debug("pin_dns=\n  " + "\n  ".join(entries))
    _pin_dns = ImmutableDict({k: (v or ()) for k, v in dns.items()})


# Not used
def _get_family(ip: str) -> int:
    ip_object = ip_address(ip)
    # Annotated, not inferred: the first branch would otherwise fix the variable
    # as AddressFamily and the 0 fallback would not fit it.
    family: int
    if ip_object.version == 4:
        family = socket.AF_INET
    elif ip_object.version == 6:
        family = socket.AF_INET6
    else:
        family = 0
    return family


# %%
def _wrap_socket_gethostbyname(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(name: str, *args: Any, **kwargs: dict[str, Any]) -> Any:
        if isinstance(name, str) and name in _pin_dns:
            for addr_info in _pin_dns[name]:
                if addr_info[0] == socket.AF_INET:
                    return addr_info[4][0]
            for addr_info in _pin_dns[name]:
                if len(addr_info) > 4 and addr_info[4]:
                    try:
                        if ip_address(addr_info[4][0]).version == 4:
                            return addr_info[4][0]
                    except (ValueError, TypeError):
                        continue
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
    @guard_wraps(func)
    def wrapper(name: str, *args: Any, **kwargs: dict[str, Any]) -> Any:
        if isinstance(name, str) and name in _pin_dns:
            addr_info = _pin_dns[name]
            can_name = addr_info[0][3] or name if addr_info else name
            return (
                can_name,
                [],
                [dns_conf[4][0] for dns_conf in _pin_dns[name] if dns_conf[0] == socket.AF_INET],
            )
        result = func(name, *args, **kwargs)
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


# Windows has no native socketpair: the stdlib emulates it with a loopback listener on an
# ephemeral port. That is the interpreter's own plumbing -- asyncio builds its event loop
# on it -- not a connection the code asked for, so no rule has to name it.
_socketpair_scope = threading.local()


def _wrap_socket_socketpair(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        previous = getattr(_socketpair_scope, "active", False)
        _socketpair_scope.active = True
        try:
            return func(*args, **kwargs)
        finally:
            _socketpair_scope.active = previous

    return wrapper


def _wrap_socket_getaddrinfo(func: Callable) -> Callable:
    @guard_wraps(func)
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


def _resolve_wildcard_host(self: Any, address: tuple[str, int]) -> tuple[str, int]:
    """Turn ``bind(("", port))`` into the wildcard address the rules are written against.

    An empty host means every interface, not a name to look up: ``getaddrinfo("")``
    always fails, so the check raised ``ValueError`` before it ever consulted a rule,
    and a guarded process could not listen at all. The profiles already spell the rule
    ``0.0.0.0/32``, which is exactly this address.
    """
    hostname, port = address[0], address[1]
    if hostname == "":
        hostname = "::" if getattr(self, "family", None) == socket.AF_INET6 else "0.0.0.0"
    return hostname, port


def _is_loopback(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _check_address(self: Any, address: tuple[str, int], conn_direction: Direction) -> None:
    if not _rules_loaded:
        return
    if getattr(_socketpair_scope, "active", False) and _is_loopback(address[0]):
        return
    _check_address_with_rules(_rules, Kind(self.type), _resolve_wildcard_host(self, address), conn_direction)


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
    @guard_wraps(func)
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
            # Binding creates a filesystem entry: require write access.
            _check_unix_socket(address, write=True, operation="bind")
        else:
            # Deny by default: an address shape we cannot interpret must not
            # reach the real syscall unchecked.
            raise RuleSocketConnectionRefusedError(
                f"Guard bind to {address!r} DENIED: unsupported address " f"format, no rule can be evaluated."
            )
        func(self, address)

    return wrapper


def _wrap_socket_connect(func: Callable) -> Callable:
    @guard_wraps(func)
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
            _check_unix_socket(address, write=False, operation="connect")
        else:
            # Was an ``assert False``, which vanishes under ``python -O``:
            # a security check must raise unconditionally.
            raise RuleSocketConnectionRefusedError(
                f"Guard connect to {address!r} DENIED: unsupported address " f"format, no rule can be evaluated."
            )
        return func(self, address)

    return wrapper


def _wrap_socket_connect_ex(func: Callable) -> Callable:
    @guard_wraps(func)
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
                _check_address(
                    self,
                    (str(address[0]), int(address[1])),
                    conn_direction=Direction.OUT,
                )
        elif isinstance(address, str):  # AF_UNIX
            _check_unix_socket(address, write=False, operation="connect_ex")
        else:
            raise RuleSocketConnectionRefusedError(
                f"Guard connect_ex to {address!r} DENIED: unsupported " f"address format, no rule can be evaluated."
            )
        return func(self, address)

    return wrapper


def _wrap_socket_sendto(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(self: Any, data: ReadableBuffer, *args: Any) -> int:
        # sendto has two documented forms: sendto(data, address) and
        # sendto(data, flags, address). The address is always the last
        # positional; flags, when present, must reach the real call untouched.
        if not args:
            return func(self, data)  # let the builtin raise its own arity error
        address: _Address = args[-1]
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
            elif self.type != Kind.TCP.value:
                # A net= rule speaks TCP or UDP only, so no rule can be
                # evaluated for any other type -- SOCK_RAW above all -- and
                # the whitelist refuses rather than letting the datagram out
                # unchecked. sendto() on a TCP socket keeps falling through:
                # the address is ignored, the OS refuses the call, and it
                # reaches nothing the connect rules did not already allow.
                raise RuleSocketConnectionRefusedError(
                    f"Guard sendto to {address!r} DENIED: socket type "
                    f"{self.type!r} cannot be evaluated by a net= rule."
                )
        elif isinstance(address, str):  # AF_UNIX
            _check_unix_socket(address, write=False, operation="sendto")
        else:
            raise RuleSocketConnectionRefusedError(
                f"Guard sendto to {address!r} DENIED: unsupported address " f"format, no rule can be evaluated."
            )
        return func(self, data, *args)

    return wrapper


def _guarded_socket_class(original: Any) -> type:
    """Publish a guarded subclass where the C module published the raw class.

    socket.socket subclasses _socket.socket and does not redefine connect, so
    patching the subclass leaves the base class method untouched: an instance
    built by `_socket.socket(...)` never consults the guard. The C type is
    immutable, so what can be replaced is the name the module publishes, and
    that is the route an attacker has to take.

    Handing back socket.socket itself recurses: socket.py line 233 calls
    `_socket.socket.__init__(self, ...)`, which would then be its own. That one
    call site is the only thing socket.py reaches through this name, so the
    subclass defines a Python __init__ forwarding to the original -- a plain
    function, so the unbound call from socket.py works whatever self is.

    The original class stays reachable through __mro__; this closes the named
    route, not the type graph.
    """

    class _GuardedSocket(original):  # type: ignore[misc,valid-type]
        # Keep the identity of the class being replaced. guard_eval grades a
        # callable by __module__, and a class defined here would report
        # pysandboxes.guard_socket, fall out of STRONG_MODULES, and be handed
        # to eval contexts that refuse the real one.
        __module__ = original.__module__
        __qualname__ = original.__qualname__

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            original.__init__(self, *args, **kwargs)

        bind = _wrap_socket_bind(original.bind)
        connect = _wrap_socket_connect(original.connect)
        connect_ex = _wrap_socket_connect_ex(original.connect_ex)
        sendto = _wrap_socket_sendto(original.sendto)

    return _GuardedSocket


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
        "_socket.socket": _guarded_socket_class,
        # socket.py does `from _socket import *`, so the resolution calls are
        # the posix relationship: `socket.gethostbyname is _socket.gethostbyname`
        # is one object under two names, and a rule on the socket name alone is
        # one `import _socket` away from being walked around. getaddrinfo is the
        # other shape -- socket.py redefines it in Python, which leaves the raw C
        # _socket.getaddrinfo unguarded rather than aliased. Both need the twin.
        "_socket.gethostbyname": _wrap_socket_gethostbyname,
        "_socket.gethostbyname_ex": _wrap_socket_gethostbyname_ex,
        "_socket.getaddrinfo": _wrap_socket_getaddrinfo,
    }
    if sys.platform == "win32":
        rules["socket.socketpair"] = _wrap_socket_socketpair
    return rules


def activate_guard(rules: SocketRules) -> None:
    """Activate socket guard with specified rules.

    Args:
        rules: Socket access rules to enforce.

    Raises:
        RuntimeError: If guard is already activated.
    """
    global _rules, _rules_loaded
    if _rules_loaded:
        raise RuntimeError("Guard_socket already activated.")
    _rules = rules
    _rules_loaded = True


def apply_pin_dns_resolution(socket_module: Any) -> None:
    """Patch resolution functions on the socket module to use _pin_dns when set.

    Use when pin_dns is non-empty but full Python sandbox (use_py_sandbox) is
    disabled, so that guest/subprocess still resolve hostnames via pinned IPs.
    """
    if not _pin_dns:
        return
    socket_module.gethostbyname = _wrap_socket_gethostbyname(socket_module.gethostbyname)
    socket_module.gethostbyname_ex = _wrap_socket_gethostbyname_ex(socket_module.gethostbyname_ex)
    socket_module.getaddrinfo = _wrap_socket_getaddrinfo(socket_module.getaddrinfo)


def _read_host_file() -> tuple[
    dict[str, set[IPv4Address | IPv6Address]],
    dict[IPv4Address | IPv6Address, set[str]],
]:
    dns: dict[str, set[IPv4Address | IPv6Address]] = {}
    inverse_dns: dict[IPv4Address | IPv6Address, set[str]] = {}
    # Read the host file
    # Detect the OS to find the correct hosts file path
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
    for host, ips in _LOOPBACK_HOSTS.items():
        if host in dns:
            continue
        for ip_str in ips:
            loopback_ip = ip_address(ip_str)
            dns.setdefault(host, set()).add(loopback_ip)
            inverse_dns.setdefault(loopback_ip, set()).add(host)
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
            in_ports = {key_for_port.get(rule.port, str(rule.port)) for rule in in_rules_for_dest}  # Can not be a range
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
                key_for_port.get(rule.port, str(rule.port)) for rule in out_rules_for_dest
            }  # Can not be a range
            rule_str = f"net=ALLOW|{kind.name}|" f"{destination}|" f"{','.join(out_ports)}|" f"{Direction.OUT.name}"
            result.add(rule_str)
    return sorted(list(result))


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_sockets() -> None:
        """Return the guard to its pre-arming state, where it enforces nothing.

        Resetting only the rules would leave a deny-all guard behind, which is not
        an inactive one: the socket wrappers stay installed for the rest of the
        process and refuse every connection a later test makes.
        """
        global _rules, _rules_loaded
        _rules = ()
        _rules_loaded = False
