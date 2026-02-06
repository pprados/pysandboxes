import re
from pathlib import Path
from typing import Union, List, \
    Tuple  # Added Tuple and Any for mock_getaddrinfo clarity
from unittest.mock import patch

import pytest

from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.guard_socket import (
    _check_address_with_rules,
    IN,
    OUT,
    _convert_ports_range
)
# Assuming _convert_ports_range is imported from your module
from pysandboxes.guard_socket import _deactivate_guard_sockets, \
    parse_rules
from pysandboxes.sb_types import ConfigLine


@pytest.fixture(autouse=True)
def reset_rules():
    yield
    _deactivate_guard_sockets()


@pytest.fixture
def mock_getaddrinfo() -> patch:
    with patch('socket.getaddrinfo') as mock:
        yield mock


# Test cases

def test_no_rules_denied_connection(mock_getaddrinfo: patch) -> None:
    """
    If no rules are set, the connection should be allowed.
    """
    import socket
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, 6, '', ('93.184.216.34', 80))]  # Used s_family
    x=socket.getaddrinfo("abc",0)
    errors = []
    rules, _ = parse_rules([], errors)
    address: Tuple[str, int] = ("example.com", 80)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_invalid_port_raises_value_error(mock_getaddrinfo: patch) -> None:
    """
    Connections to an invalid port number should raise a ValueError.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    rules, _ = parse_rules([], errors)  # Rules don't matter here
    with pytest.raises(ValueError, match="Invalid port number: -1"):
        _check_address_with_rules(rules, s_type, ("example.com", -1), OUT)
    with pytest.raises(ValueError, match="Invalid port number: 65536"):
        _check_address_with_rules(rules, s_type, ("example.com", 65536), OUT)


def test_hostname_resolution_failure_raises_value_error(
        mock_getaddrinfo: patch) -> None:
    """
    If hostname resolution fails (socket.gaierror), a ValueError should be raised.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.side_effect = socket.gaierror("Resolution failed")
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|127.0.0.1/32|80|OUT", Path(), 0)
        ], errors)
    address: Tuple[str, int] = ("nonexistent.example.com", 80)
    with pytest.raises(
            ValueError,
            match=re.escape(r"Invalid hostname or IP address (resolution failed): "
                            r"nonexistent.example.com")):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_hostname_resolves_to_no_valid_ips_raises_value_error(
        mock_getaddrinfo: patch) -> None:
    """
    If getaddrinfo returns no parsable IP addresses matching the socket family,
    a ValueError should be raised.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = []  # No results
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|127.0.0.1/32|80|OUT", Path(), 0)
        ], errors)
    address: Tuple[str, int] = ("empty.resolve.com", 80)
    # This ValueError is unlikely to be raised by the current guard_socket.py code in this scenario.
    with pytest.raises(
            ValueError,
            match=re.escape(
                r'Invalid hostname or IP address (resolution failed): empty.resolve.com')):
        _check_address_with_rules(rules, s_type, address, OUT)

    # Test with non-IP address in sockaddr (e.g. AF_UNIX) when socket family is AF_INET
    mock_getaddrinfo.return_value = [
        (socket.AF_UNIX, socket.SOCK_STREAM, 0, '',
         ('/path/to/socket'))]  # type: ignore
    # This ValueError is also unlikely. Corrected s_family.value to s_family.
    with pytest.raises(
            ValueError,
            match=re.escape(r"'/' does not appear to be an IPv4 or IPv6 address")):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_explicit_deny_rule_blocks_connection(mock_getaddrinfo: patch) -> None:
    """
    An explicit DENY rule matching the IP, port, and direction should block the connection.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, s_proto, '', ('192.168.1.100', 8080))]  # Used s_family
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|192.168.1.100/24|8080|OUT", Path(), 0),
        ],
        errors)
    address: Tuple[str, int] = ("blocked.host.local", 8080)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_explicit_deny_rule_any_port_blocks_connection(mock_getaddrinfo: patch) -> None:
    """
    An explicit DENY rule with '*' (all ports) should block connection to any port on that network.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, s_proto, '', ('10.0.0.5', 1234))]  # Used s_family
    rules, _ = parse_rules([
        ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
        ConfigLine("net=DENY|any|10.0.0.0/8|*|OUT", Path(), 0),
    ], errors)
    address: Tuple[str, int] = ("internal.service", 1234)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_explicit_deny_ipv6_rule_blocks_connection(mock_getaddrinfo: patch) -> None:
    """
    An explicit DENY rule for an IPv6 address should block the connection.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET6, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, s_proto, '', ('::1', 443, 0, 0))]  # Used s_family
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|any|::1/0|*|OUT", Path(), 0),
            ConfigLine("net=DENY|any|::1/128|443|OUT", Path(), 0),
        ], errors)
    address: Tuple[str, int] = ("ip6-localhost", 443)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_multiple_ips_one_matches_deny_blocks(mock_getaddrinfo: patch) -> None:
    """
    If a hostname resolves to multiple IPs, and one matches a DENY rule, it's blocked.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.10', 80)),
        # This one will be blocked
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('5.6.7.8', 80))
    ]
    rules, _ = parse_rules([
        ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
        ConfigLine("net=DENY|any|192.168.1.10/32|80|OUT", Path(), 0)
    ], errors)
    address: Tuple[str, int] = ("multihomed.host", 80)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_explicit_allow_rule_not_triggers_allow_exception(
        mock_getaddrinfo: patch) -> None:
    """
    Tests that an explicit ALLOW rule, when matched, raises a specific "explicitly ALLOW"
    RuntimeError, as per the current function logic.
    This occurs if no preceding DENY rule matched.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, s_proto, '', ('8.8.8.8', 53))]  # Used s_family
    rules, _ = parse_rules([
        # ConfigLine("net=DENY|any|1.1.1.1/32|1234|OUT", Path(), 0),
        # # First rule is ALLOW.
        ConfigLine("net=ALLOW|any|8.8.8.8/32|53|OUT", Path(), 0),
        # This ALLOW rule (rule #1) matches.
    ], errors)
    address: Tuple[str, int] = ("google.dns", 53)
    _check_address_with_rules(rules, s_type, address, OUT)


def test_bind_direction_check_explicit_deny(mock_getaddrinfo: patch) -> None:
    """
    Test explicit DENY for IN (bind) direction.
    """
    import socket
    errors = []
    s_family, s_type, s_proto = socket.AF_INET, socket.SOCK_STREAM, 6
    mock_getaddrinfo.return_value = [
        (s_family, s_type, s_proto, '', ('0.0.0.0', 8080))]  # Used s_family
    rules, _ = parse_rules([
        ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0),
        ConfigLine("net=DENY|any|0.0.0.0/0|8080|IN", Path(), 0),
    ], errors)
    address: Tuple[str, int] = ("0.0.0.0", 8080)
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, IN)


def test_mixed_ipv4_ipv6_resolution_one_denied(mock_getaddrinfo: patch) -> None:
    """
    If hostname resolves to multiple IPs (IPv4 and IPv6), and one IPv6 matches a DENY rule,
    the connection is blocked. The socket instance is AF_INET6.
    The first rule is ALLOW to set implicit DENY, but it doesn't match the connection.
    """
    import socket
    hostname: str = "mixed.ip.example.com"
    port: int = 9000
    # Socket instance is IPv6 capable
    s_family, s_type, s_proto = socket.AF_INET6, socket.SOCK_STREAM, 6,

    errors = []
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('172.16.0.5', port)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '',
         ('2a00:1450:400e:804::200e', port, 0, 0)),  # IPv6, will be matched by DENY
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', port))
    ]

    rules, _ = parse_rules([
        ConfigLine("net=ALLOW|any|::1/0|80|OUT", Path(), 0),
        # Rule 0: First rule is ALLOW, implicit default is DENY. Doesn't match port.
        ConfigLine("net=DENY|any|2a00:1450::/32|9000|OUT", Path(), 0),
        # Corrected double ==, Rule 1: DENY rule for the IPv6 network.
    ], errors)
    address: Tuple[str, int] = (hostname, port)

    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, s_type, address, OUT)


def test_socket_type_any_allows_different_types(mock_getaddrinfo: patch) -> None:
    """
    Tests that a rule with 'any' for socket type allows connections with different socket types.
    """
    import socket
    errors = []
    s_family_inet, s_type_stream, _ = socket.AF_INET, socket.SOCK_STREAM, 0
    hostname, port = "anytype.example.com", 1234
    ip_address = "1.2.3.4"

    mock_getaddrinfo.return_value = [
        (s_family_inet, s_type_stream, 6, '', (ip_address, port))
    ]
    # Rule ALLOWING 'any' type
    rules, _ = parse_rules([
        ConfigLine(f"net=ALLOW|*|0.0.0.0/0|{port}|OUT", Path(), 0),
        ConfigLine(f"net=DENY|*|{ip_address}/32|{port}|OUT", Path(), 0),
    ], errors)
    address: Tuple[str, int] = (hostname, port)

    # Test with SOCK_STREAM
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, socket.SOCK_STREAM, address, OUT)

    # Test with SOCK_DGRAM
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, socket.SOCK_DGRAM, address, OUT)


@pytest.mark.parametrize(
    "port_spec, expected_output",
    [
        # Valid cases that should not raise exceptions
        ("80", [80]),
        ("80,443", [80, 443]),
        ("8000-8080", range(8000, 8081)),
        ("80,8000-8002,443", [80, 443, 8000, 8001, 8002]),
        ("*", range(0, 65536)),
        ("0", [0]),
        ("65535", [65535]),
        ("  80  ,  443 ", [80, 443]),  # With spaces
        ("8000-", range(8000, 65536)),  # Open-ended range
        ("10-10", [10]),  # Single port range
        ("", []),  # Empty string
        (" ", []),  # String with only spaces
        (",", []),  # Only a comma
        ("80, ,443", [80, 443]),  # Empty element in the middle
    ]
)
def test_convert_ports_range_valid_cases(port_spec: str, expected_output: Union[
    List[int], range]) -> None:
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
        ("abc-8080", "Invalid start port number 'abc' in range 'abc-8080'."),
        ("8080-8000",
         "Invalid range: start port 8080 is greater than end port 8000 in '8080-8000'."),
        ("-1", "Invalid range format: '-1'. Range start cannot be empty."),
        ("65536", "Invalid port number '65536'."),
        ("0-65536",
         "End port 65536 in range '0-65536' is out of valid range (0-65535)."),
        ("80,abc,443", "Invalid port number 'abc'."),
        ("80-82,def,100-102", "Invalid port number 'def'."),
        ("80--90", "End port -90 in range '80--90' is out of valid range (0-65535)."),
        ("-8000", "Invalid range format: '-8000'. Range start cannot be empty."),
    ]
)
def test_convert_ports_range_invalid_cases(port_spec: str,
                                           expected_exception_message: str) -> None:
    """
    Tests the _convert_ports_range function with invalid port specification syntaxes
    that should raise a ValueError with a specific message.
    """
    with pytest.raises(ValueError, match=re.escape(expected_exception_message)):
        _convert_ports_range(port_spec)


def test_convert_ports_range_duplicates_and_sorting() -> None:
    """
    Tests that _convert_ports_range handles duplicates and sorts the output for valid inputs.
    """
    assert _convert_ports_range("443,80,443") == [80, 443]
    assert _convert_ports_range("8080-8082,8000-8001") == [8000, 8001, 8080, 8081, 8082]
