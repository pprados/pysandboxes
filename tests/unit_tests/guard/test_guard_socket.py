import re
from pathlib import Path
from socket import AddressFamily, SocketKind
from typing import (
    Any,
    Callable,
    Iterator,
    List,
    Tuple,
    Union,
    cast,
)

# Added Tuple and Any for mock_getaddrinfo clarity
from unittest.mock import Mock, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.guard_socket import (
    AddrInfoType,
    Direction,
    Kind,
    _check_address_with_rules,
    _convert_ports_range,
    activate_guard,
    parse_rules,
    patch_rules,
)
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine


@pytest.fixture
def mock_getaddrinfo() -> Iterator[Mock]:
    with patch("pysandboxes.guard_socket.getaddrinfo") as mock:
        yield mock


# Test cases


def test_no_rules_denied_connection(mock_getaddrinfo: Mock) -> None:
    """
    If no rules are set, the connection should be allowed.
    """
    from pysandboxes.guard_socket import socket

    s_family, s_kind = (
        socket.AF_INET,
        Kind.TCP,
    )
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("93.184.216.34", 80))]  # Used s_family
    errors: List[ErrorMsg] = []
    rules, *_ = parse_rules([], errors)
    address: Tuple[str, int] = ("example.com", 80)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_invalid_port_raises_value_error(mock_getaddrinfo: Mock) -> None:
    """
    Connections to an invalid port number should raise a ValueError.
    """
    errors: List[ErrorMsg] = []
    s_kind = Kind.TCP
    rules, *_ = parse_rules([], errors)  # Rules don't matter here
    with pytest.raises(ValueError, match="Invalid port number: -1"):
        _check_address_with_rules(rules, s_kind, ("example.com", -1), Direction.OUT)
    with pytest.raises(ValueError, match="Invalid port number: 65536"):
        _check_address_with_rules(rules, s_kind, ("example.com", 65536), Direction.OUT)


def test_hostname_resolution_failure_raises_value_error(
    mock_getaddrinfo: Mock,
) -> None:
    """
    If hostname resolution fails (socket.gaierror), a ValueError should be raised.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_kind = Kind.TCP
    mock_getaddrinfo.side_effect = socket.gaierror("Resolution failed")
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|127.0.0.1/32|80|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("nonexistent.example.com", 80)
    with pytest.raises(
        ValueError,
        match=re.escape(r"Invalid hostname or IP address (resolution failed): " r"nonexistent.example.com"),
    ):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)
    pass


def test_hostname_resolves_to_no_valid_ips_raises_value_error(
    mock_getaddrinfo: Mock,
) -> None:
    """
    If getaddrinfo returns no parsable IP addresses matching the socket family,
    a ValueError should be raised.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_kind = Kind.TCP
    # with patch("pysandboxes.guard_socket.socket.getaddrinfo") as mock_getaddrinfo:
    mock_getaddrinfo.return_value = []  # No results
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|127.0.0.1/32|80|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("empty.resolve.com", 80)
    # This ValueError is unlikely to be raised by the current guard_socket.py code
    # in this scenario.
    with pytest.raises(
        ValueError,
        match=re.escape(r"Invalid hostname or IP address (resolution failed): empty.resolve.com"),
    ):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)

    # Test with non-IP address in sockaddr (e.g. AF_UNIX) when socket family is AF_INET
    mock_getaddrinfo.return_value = [(socket.AF_UNIX, Kind.TCP.value, 0, "", ("/path/to/socket"))]  # type: ignore
    # This ValueError is also unlikely. Corrected s_family.value to s_family.
    with pytest.raises(
        ValueError,
        match=re.escape(r"'/' does not appear to be an IPv4 or IPv6 address"),
    ):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_explicit_deny_rule_blocks_connection(mock_getaddrinfo: Mock) -> None:
    """
    An explicit DENY rule matching the IP, port, and directions should
    block the connection.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("192.168.1.100", 8080))]  # Used s_family
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|192.168.1.100/24|8080|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("blocked.host.local", 8080)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_explicit_deny_rule_any_port_blocks_connection(mock_getaddrinfo: Mock) -> None:
    """
    An explicit DENY rule with '*' (all ports) should block connection to any port
    on that network.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("10.0.0.5", 1234))]  # Used s_family
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|tcp,udp|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|10.0.0.0/8|*|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("internal.service", 1234)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_accept_all_syntaxes(mock_getaddrinfo: Mock) -> None:
    """
    An explicit DENY rule with '*' (all ports) should block connection to any
    port on that network.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("10.0.0.5", 1234))]  # Used s_family
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|tcp,udp|0.0.0.0/0|*|*", Path(), 0),
            ConfigLine("net=ALLOW|*|*|*|*", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("internal.service", 1234)
    _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_explicit_deny_ipv6_rule_blocks_connection(mock_getaddrinfo: Mock) -> None:
    """
    An explicit DENY rule for an IPv6 address should block the connection.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET6, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("::1", 443, 0, 0))]  # Used s_family
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|::1/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|::1/128|443|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("ip6-localhost", 443)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_multiple_ips_one_matches_deny_blocks(mock_getaddrinfo: Mock) -> None:
    """
    If a hostname resolves to multiple IPs, and one matches a DENY rule, it's blocked.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_kind = Kind.TCP
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, s_kind, 6, "", ("1.2.3.4", 80)),
        (socket.AF_INET, s_kind, 6, "", ("192.168.1.10", 80)),
        # This one will be blocked
        (socket.AF_INET, s_kind, 6, "", ("5.6.7.8", 80)),
    ]
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|192.168.1.10/32|80|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("multihomed.host", 80)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_explicit_allow_rule_not_triggers_allow_exception(
    mock_getaddrinfo: Mock,
) -> None:
    """
    Tests that an explicit ALLOW rule, when matched, raises a specific
    "explicitly ALLOW"
    RuntimeError, as per the current function logic.
    This occurs if no preceding DENY rule matched.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("8.8.8.8", 53))]  # Used s_family
    rules, *_ = parse_rules(
        [
            # ConfigLine("net=DENY|any|1.1.1.1/32|1234|OUT", Path(), 0),
            # # First rule is ALLOW.
            ConfigLine("net=ALLOW|any|8.8.8.8/32|53|OUT", Path(), 0),
            # This ALLOW rule (rule #1) matches.
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("google.pin_dns", 53)
    _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_bind_direction_check_explicit_deny(mock_getaddrinfo: Mock) -> None:
    """
    Test explicit DENY for IN (bind) directions.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_family, s_kind = socket.AF_INET, Kind.TCP
    mock_getaddrinfo.return_value = [(s_family, s_kind, 6, "", ("0.0.0.0", 8080))]  # Used s_family
    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|0.0.0.0/0|8080|IN", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = ("0.0.0.0", 8080)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.IN)


def test_mixed_ipv4_ipv6_resolution_one_denied(mock_getaddrinfo: Mock) -> None:
    """
    If hostname resolves to multiple IPs (IPv4 and IPv6), and one IPv6 matches a
    DENY rule,
    the connection is blocked. The socket instance is AF_INET6.
    The first rule is ALLOW to set implicit DENY, but it doesn't match the connection.
    """
    from pysandboxes.guard_socket import socket

    hostname: str = "mixed.ip.example.com"
    port: int = 9000
    # Socket instance is IPv6 capable

    errors: List[ErrorMsg] = []
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, Kind.TCP, 6, "", ("172.16.0.5", port)),
        (
            socket.AF_INET6,
            Kind.TCP,
            6,
            "",
            ("2a00:1450:400e:804::200e", port, 0, 0),
        ),  # IPv6, will be matched by DENY
        (socket.AF_INET, Kind.TCP, 6, "", ("10.0.0.1", port)),
    ]

    rules, *_ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|::1/0|80|OUT", Path(), 0),
            # Rule 0: First rule is ALLOW, implicit default is DENY. Doesn't match port.
            ConfigLine("net=DENY|any|2a00:1450::/32|9000|OUT", Path(), 0),
            # Corrected double ==, Rule 1: DENY rule for the IPv6 network.
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = (hostname, port)
    s_kind = Kind.TCP

    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_kind, address, Direction.OUT)


def test_socket_type_any_allows_different_types(mock_getaddrinfo: Mock) -> None:
    """
    Tests that a rule with 'any' for socket type allows connections with
    different socket kinds.
    """
    from pysandboxes.guard_socket import socket

    errors: List[ErrorMsg] = []
    s_kind = Kind.TCP
    hostname, port = "anytype.example.com", 1234
    ip_address = "1.2.3.4"

    mock_getaddrinfo.return_value = [(socket.AF_INET, s_kind, 6, "", (ip_address, port))]
    # Rule ALLOWING 'any' type
    rules, *_ = parse_rules(
        [
            ConfigLine(f"net=ALLOW|*|0.0.0.0/0|{port}|OUT", Path(), 0),
            ConfigLine(f"net=DENY|*|{ip_address}/32|{port}|OUT", Path(), 0),
        ],
        errors,
    )
    assert not errors
    address: Tuple[str, int] = (hostname, port)

    # Test with SOCK_STREAM
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, Kind.TCP, address, Direction.OUT)

    # Test with SOCK_DGRAM
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, Kind.UDP, address, Direction.OUT)


@pytest.mark.parametrize(
    "port_spec, expected_output",
    [
        # Valid cases that should not raise exceptions
        ("80", (80,)),
        ("80,443", (80, 443)),
        ("8000-8080", range(8000, 8081)),
        ("80,8000-8002,443", (80, 443, 8000, 8001, 8002)),
        ("*", range(0, 65536)),
        ("0", (0,)),
        ("65535", (65535,)),
        ("  80  ,  443 ", (80, 443)),  # With spaces
        ("8000-", range(8000, 65536)),  # Open-ended range
        ("10-10", (10,)),  # Single port range
        ("", ()),  # Empty string
        (" ", ()),  # String with only spaces
        (",", ()),  # Only a comma
        ("80, ,443", (80, 443)),  # Empty element in the middle
    ],
)
def test_convert_ports_range_valid_cases(port_spec: str, expected_output: Union[int, Tuple[int, ...], range]) -> None:
    """
    Tests the _convert_ports_range function with valid port specification syntaxes
    that should return a list or range of ports without raising an exception.
    """
    result = _convert_ports_range(port_spec)
    assert result == expected_output


@pytest.mark.parametrize(
    "port_spec, expected_exception_message",
    [
        # Invalid cases that should raise ValueError
        ("abc", "Invalid port number 'abc'."),
        ("80-abc", "Invalid end port number 'abc' in range '80-abc'."),
        ("abc-8080", "Invalid _start port number 'abc' in range 'abc-8080'."),
        (
            "8080-8000",
            "Invalid range: _start port 8080 is greater than end port 8000 in '8080-8000'.",  # noqa: E501
        ),
        ("-1", "Invalid range format: '-1'. Range _start cannot be empty."),
        ("65536", "Invalid port number '65536'."),
        (
            "0-65536",
            "End port 65536 in range '0-65536' is out of valid range (0-65535).",
        ),
        ("80,abc,443", "Invalid port number 'abc'."),
        ("80-82,def,100-102", "Invalid port number 'def'."),
        ("80--90", "End port -90 in range '80--90' is out of valid range (0-65535)."),
        ("-8000", "Invalid range format: '-8000'. Range _start cannot be empty."),
    ],
)
def test_convert_ports_range_invalid_cases(port_spec: str, expected_exception_message: str) -> None:
    """
    Tests the _convert_ports_range function with invalid port specification syntaxes
    that should raise a ValueError with a specific message.
    """
    with pytest.raises(ValueError, match=re.escape(expected_exception_message)):
        _convert_ports_range(port_spec)


def test_convert_ports_range_duplicates_and_sorting() -> None:
    """
    Tests that _convert_ports_range handles duplicates and sorts the output for
    valid inputs.
    """
    assert _convert_ports_range("443,80,443") == (80, 443)
    assert _convert_ports_range("8080-8082,8000-8001") == (8000, 8001, 8080, 8081, 8082)


class _FakeSocket:
    """Stand-in for a socket object: the wrappers only read ``type``.

    SOCK_RAW needs CAP_NET_RAW, so a real socket would make the test
    root-only for no gain.
    """

    def __init__(self, kind: SocketKind) -> None:
        self.type = kind


def _arm(*rules: str) -> None:
    """Arm the socket guard with the given ``net=`` rules."""
    errors: List[ErrorMsg] = []
    lines = [ConfigLine(rule, Path(), ln) for ln, rule in enumerate(rules)]
    socket_rules, _, _ = parse_rules(lines, errors)
    assert not errors
    activate_guard(socket_rules)


def _guarded(qualname: str) -> Callable[..., Any]:
    """Build the wrapper the patch table would install."""
    return patch_rules(learn=False)[qualname](lambda *a, **k: "called")


def test_connect_ex_enforces_the_rules() -> None:
    """connect_ex() reached a method that does not exist, never the rules."""
    _arm("net=ALLOW|TCP|127.0.0.1|80|OUT")
    wrapped = _guarded("socket.socket.connect_ex")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    assert wrapped(sock, ("127.0.0.1", 80)) == "called"
    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, ("127.0.0.1", 8080))


def test_connect_enforces_the_rules() -> None:
    """The same coverage for connect(), which decides IN vs OUT itself."""
    _arm("net=ALLOW|TCP|127.0.0.1|80|OUT")
    wrapped = _guarded("socket.socket.connect")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    assert wrapped(sock, ("127.0.0.1", 80)) == "called"
    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, ("127.0.0.1", 8080))


def test_sendto_enforces_the_udp_rules() -> None:
    _arm("net=ALLOW|UDP|127.0.0.1|12345|OUT")
    wrapped = _guarded("socket.socket.sendto")
    sock = _FakeSocket(SocketKind.SOCK_DGRAM)

    assert wrapped(sock, b"x", ("127.0.0.1", 12345)) == "called"
    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, b"x", ("127.0.0.1", 9999))


def test_sendto_refuses_a_socket_type_no_rule_can_express() -> None:
    """SOCK_RAW used to fall through to the real sendto, unfiltered."""
    _arm("net=ALLOW|UDP|127.0.0.1|12345|OUT")
    wrapped = _guarded("socket.socket.sendto")

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(_FakeSocket(SocketKind.SOCK_RAW), b"x", ("127.0.0.1", 12345))


def test_sendto_refuses_an_unsupported_address_format() -> None:
    _arm("net=ALLOW|UDP|127.0.0.1|12345|OUT")
    wrapped = _guarded("socket.socket.sendto")

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(_FakeSocket(SocketKind.SOCK_DGRAM), b"x", b"\x00raw")


def test_invalid_sendTo() -> None:
    """
    Test if a invalid sendTo continue to raise an exception
    """
    from pysandboxes.guard_socket import socket

    with pytest.raises(BrokenPipeError):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:  # Invalid type
            sock.sendto(b"hello", ("127.0.0.1", 12345))


def test_getaddrinfo() -> None:
    from socket import getaddrinfo

    default_values = [
        (
            AddressFamily.AF_INET6,
            SocketKind.SOCK_STREAM,
            6,
            "",
            ("2a00:1450:4007:809::2004", 0, 0, 0),
        ),
        (
            AddressFamily.AF_INET6,
            SocketKind.SOCK_DGRAM,
            17,
            "",
            ("2a00:1450:4007:809::2004", 0, 0, 0),
        ),
        (
            AddressFamily.AF_INET6,
            SocketKind.SOCK_RAW,
            0,
            "",
            ("2a00:1450:4007:809::2004", 0, 0, 0),
        ),
        (
            AddressFamily.AF_INET,
            SocketKind.SOCK_STREAM,
            6,
            "",
            ("142.250.179.68", 0, 0, 0),
        ),
        (
            AddressFamily.AF_INET,
            SocketKind.SOCK_DGRAM,
            17,
            "",
            ("142.250.179.68", 0, 0, 0),
        ),
        (
            AddressFamily.AF_INET,
            SocketKind.SOCK_RAW,
            0,
            "",
            ("142.250.179.68", 0, 0, 0),
        ),
    ]
    import pysandboxes.guard_socket

    pysandboxes.guard_socket._pin_dns = cast(
        ImmutableDict[str, tuple[AddrInfoType, ...]],
        ImmutableDict({"www.google.com": default_values}),
    )

    assert getaddrinfo("www.google.com", 0) == pysandboxes.guard_socket._pin_dns["www.google.com"]
    assert all(x[4][1] == 80 for x in getaddrinfo("www.google.com", 80))
    assert all(x[0] == AddressFamily.AF_INET for x in getaddrinfo("www.google.com", 0, family=AddressFamily.AF_INET))
    assert all(x[1] == SocketKind.SOCK_STREAM for x in getaddrinfo("www.google.com", 0, type=SocketKind.SOCK_STREAM))
    assert all(x[2] == 6 for x in getaddrinfo("www.google.com", 0, proto=6))
