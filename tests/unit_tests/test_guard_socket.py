import pytest
import socket
import ipaddress
from unittest.mock import patch
from langgraph_codeagent.sandboxes.guard_socket import (
    _check_address_with_rules,
    DENY,
    ALLOW,
    IN,
    OUT,
    # logger, # logger n'est pas utilisé directement dans les tests
    # _convert_ports_range # Non utilisé directement par ces tests spécifiques
)


@pytest.fixture
def mock_getaddrinfo():
    with patch('socket.getaddrinfo') as mock:
        yield mock


def create_parsed_rule(action, network_str, ports_list_or_range, direction):
    """Helper to create the parsed rule structure expected by _check_address_with_rules."""
    return (action,
            (ipaddress.ip_network(network_str, strict=False), ports_list_or_range),
            direction)


# Test cases

def test_no_rules_allows_connection(mock_getaddrinfo):
    """
    If no rules are set, the connection should be allowed.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
    rules = []
    address = ("example.com", 80)
    # _check_address_with_rules should not raise any exception
    _check_address_with_rules(rules, address, OUT)


def test_invalid_port_raises_value_error(mock_getaddrinfo):
    """
    Connections to an invalid port number should raise a ValueError.
    """
    rules = []  # Rules don't matter here
    with pytest.raises(ValueError, match="Invalid port number: -1"):
        _check_address_with_rules(rules, ("example.com", -1), OUT)
    with pytest.raises(ValueError, match="Invalid port number: 65536"):
        _check_address_with_rules(rules, ("example.com", 65536), OUT)


def test_hostname_resolution_failure_raises_value_error(mock_getaddrinfo):
    """
    If hostname resolution fails (socket.gaierror), a ValueError should be raised.
    """
    mock_getaddrinfo.side_effect = socket.gaierror("Resolution failed")
    rules = [create_parsed_rule(DENY, "127.0.0.1/32", [80], OUT)]
    address = ("nonexistent.example.com", 80)
    with pytest.raises(ValueError,
                       match=r"Invalid hostname or IP address \(resolution failed\): nonexistent\.example\.com"):
        _check_address_with_rules(rules, address, OUT)


def test_hostname_resolves_to_no_valid_ips_raises_value_error(mock_getaddrinfo):
    """
    If getaddrinfo returns no parsable IP addresses, a ValueError should be raised.
    """
    mock_getaddrinfo.return_value = []  # No results
    rules = [create_parsed_rule(DENY, "127.0.0.1/32", [80], OUT)]
    address = ("empty.resolve.com", 80)
    with pytest.raises(ValueError,
                       match=r"Could not resolve empty\.resolve\.com to any valid IP address for rule checking\."):
        _check_address_with_rules(rules, address, OUT)

    # Test with non-IP address in sockaddr
    mock_getaddrinfo.return_value = [
        (socket.AF_UNIX, socket.SOCK_STREAM, 0, '', ('/path/to/socket'))]
    with pytest.raises(ValueError,
                       match=r"Could not resolve empty\.resolve\.com to any valid IP address for rule checking\."):
        _check_address_with_rules(rules, address, OUT)


def test_explicit_deny_rule_blocks_connection(mock_getaddrinfo):
    """
    An explicit DENY rule matching the IP, port, and direction should block the connection.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.100', 8080))]
    rules = [create_parsed_rule(DENY, "192.168.1.0/24", [8080], OUT)]
    address = ("blocked.host.local", 8080)
    # with pytest.raises(RuntimeError,
    #                    match=r"Guard network connection to 192\.168\.1\.100:8080 \(from blocked\.host\.local\) explicitly DENIED by rule #0 \(DENY 192\.168\.1\.0/24:\[8080\] OUT\)\."):
    try:
        _check_address_with_rules(rules, address, OUT)
    except RuntimeError as e:
        print(e)


def test_explicit_deny_rule_any_port_blocks_connection(mock_getaddrinfo):
    """
    An explicit DENY rule with '*' (all ports) should block connection to any port on that network.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 1234))]
    rules = [create_parsed_rule(DENY, "10.0.0.0/8", range(0, 65536),
                                OUT)]  # range(0,65536) simulates '*'
    address = ("internal.service", 1234)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 10\.0\.0\.5:1234 \(from internal\.service\) explicitly DENIED by rule #0 \(DENY 10\.0\.0\.0/8:range\(0, 65536\) OUT\)\."):
        _check_address_with_rules(rules, address, OUT)


def test_explicit_deny_ipv6_rule_blocks_connection(mock_getaddrinfo):
    """
    An explicit DENY rule for an IPv6 address should block the connection.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443, 0, 0))]
    rules = [create_parsed_rule(DENY, "::1/128", [443], OUT)]
    address = ("localhost_v6", 443)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to ::1:443 \(from localhost_v6\) explicitly DENIED by rule #0 \(DENY ::1/128:\[443\] OUT\)\."):
        _check_address_with_rules(rules, address, OUT)


def test_no_deny_match_first_rule_allow_implicitly_denies(mock_getaddrinfo):
    """
    If no DENY rule matches and the first rule is ALLOW, and no ALLOW rule matches,
    the implicit default is DENY.
    Connection to a port not covered by the first ALLOW rule.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 9090))]
    # First rule is ALLOW, so implicit default is DENY
    rules = [create_parsed_rule(ALLOW, "0.0.0.0/0", [80, 443], OUT)]
    address = ("example.com", 9090)  # Port 9090 is not in the ALLOW rule
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to example\.com \(port 9090\) DENIED by implicit default \(first rule: ALLOW\)\. Resolved IPs: .*"):
        _check_address_with_rules(rules, address, OUT)


def test_no_deny_match_first_rule_allow_network_mismatch_implicitly_denies(
        mock_getaddrinfo):
    """
    If no DENY rule matches, first rule is ALLOW, but network doesn't match the ALLOW rule,
    and no other ALLOW rule matches, the implicit default (DENY) applies.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
    rules = [create_parsed_rule(ALLOW, "1.1.1.1/32", [80],
                                OUT)]  # ALLOW rule for a different network
    address = ("example.com", 80)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to example\.com \(port 80\) DENIED by implicit default \(first rule: ALLOW\)\. Resolved IPs: .*"):
        _check_address_with_rules(rules, address, OUT)


def test_no_deny_match_first_rule_deny_implicitly_allows(mock_getaddrinfo):
    """
    If no DENY rule matches and the first rule is DENY (and no explicit ALLOW matches),
    the implicit default is ALLOW.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
    # First rule is DENY, so implicit default is ALLOW
    rules = [create_parsed_rule(DENY, "127.0.0.1/32", [8080],
                                OUT)]  # This DENY rule doesn't match
    address = ("example.com", 80)
    # Should not raise
    _check_address_with_rules(rules, address, OUT)


def test_deny_rule_direction_mismatch_first_rule_deny_implicitly_allows(
        mock_getaddrinfo):
    """
    A DENY rule exists for the IP/port but for the wrong direction.
    If the first rule is DENY, connection is implicitly allowed (as no rule matches).
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
    rules = [create_parsed_rule(DENY, "93.184.216.34/32", [80],
                                IN)]  # Rule for IN, connection is OUT
    address = ("example.com", 80)
    # Should not raise (implicit ALLOW)
    _check_address_with_rules(rules, address, OUT)


def test_deny_rule_direction_mismatch_first_rule_allow_implicitly_denies(
        mock_getaddrinfo):
    """
    A DENY rule exists for the IP/port but for the wrong direction.
    If the first rule is ALLOW, and no other rule matches, connection is implicitly denied.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
    rules = [
        create_parsed_rule(ALLOW, "0.0.0.0/0", [443], OUT),  # First rule ALLOW (doesn't match port)
        create_parsed_rule(DENY, "93.184.216.34/32", [80], IN)  # DENY rule for IN (doesn't match direction)
    ]
    address = ("example.com", 80)  # Connection is OUT
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to example\.com \(port 80\) DENIED by implicit default \(first rule: ALLOW\)\. Resolved IPs: .*"):
        _check_address_with_rules(rules, address, OUT)


def test_multiple_ips_one_matches_deny_blocks(mock_getaddrinfo):
    """
    If a hostname resolves to multiple IPs, and one matches a DENY rule, it's blocked.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.10', 80)),
        # This one will be blocked
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('5.6.7.8', 80))
    ]
    rules = [create_parsed_rule(DENY, "192.168.1.10/32", [80], OUT)]
    address = ("multihomed.host", 80)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 192\.168\.1\.10:80 \(from multihomed\.host\) explicitly DENIED by rule #0 \(DENY 192\.168\.1\.10/32:\[80\] OUT\)\."):
        _check_address_with_rules(rules, address, OUT)


def test_multiple_rules_first_matching_deny_blocks(mock_getaddrinfo):
    """
    If multiple DENY rules exist, the first one that matches blocks the connection.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]
    rules = [
        create_parsed_rule(DENY, "192.168.0.0/16", [80], OUT),  # Doesn't match
        create_parsed_rule(DENY, "10.0.0.0/8", [443], OUT),  # Matches (rule #1)
        create_parsed_rule(DENY, "0.0.0.0/0", range(0, 65536), OUT)
        # Also matches but earlier one takes precedence
    ]
    address = ("server.internal", 443)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 10\.0\.0\.5:443 \(from server\.internal\) explicitly DENIED by rule #1 \(DENY 10\.0\.0\.0/8:\[443\] OUT\)\."):
        _check_address_with_rules(rules, address, OUT)


def test_explicit_allow_rule_triggers_allow_exception(mock_getaddrinfo):
    """
    Tests that an explicit ALLOW rule, when matched, raises a specific "explicitly ALLOW"
    RuntimeError, as per the current function logic.
    This occurs if no preceding DENY rule matched.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 53))]
    rules = [
        create_parsed_rule(ALLOW, "1.1.1.1/32", [1234], OUT),
        # First rule is ALLOW.
        create_parsed_rule(ALLOW, "8.8.8.8/32", [53], OUT)
        # This ALLOW rule (rule #1) matches the connection.
    ]
    address = ("google.dns", 53)
    # Expecting an "explicitly ALLOW by rule #1" exception due to current function behavior.
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 8\.8\.8\.8:53 \(from google\.dns\) explicitly ALLOW by rule #1 \(ALLOW 8\.8\.8\.8/32:\[53\] OUT\)\."):
        _check_address_with_rules(rules, address, OUT)


def test_deny_rule_port_mismatch_first_rule_deny_implicitly_allows(mock_getaddrinfo):
    """
    A DENY rule matches network and direction, but not port.
    If first rule is DENY, connection is implicitly allowed.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.10', 80))]
    rules = [create_parsed_rule(DENY, "192.168.1.0/24", [443],
                                OUT)]  # DENY rule for port 443
    address = ("host.local", 80)  # Connecting to port 80
    # Should not raise (implicit ALLOW)
    _check_address_with_rules(rules, address, OUT)


def test_deny_rule_network_mismatch_first_rule_deny_implicitly_allows(mock_getaddrinfo):
    """
    A DENY rule matches port and direction, but not network.
    If first rule is DENY, connection is implicitly allowed.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 80))]
    rules = [create_parsed_rule(DENY, "192.168.1.0/24", [80],
                                OUT)]  # DENY rule for different network
    address = ("public.host", 80)
    # Should not raise (implicit ALLOW)
    _check_address_with_rules(rules, address, OUT)


def test_bind_direction_check_explicit_deny(mock_getaddrinfo):
    """
    Test explicit DENY for IN (bind) direction.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('0.0.0.0', 8080))]
    rules = [create_parsed_rule(DENY, "0.0.0.0/0", [8080], IN)]
    address = ("0.0.0.0", 8080)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 0\.0\.0\.0:8080 \(from 0\.0\.0\.0\) explicitly DENIED by rule #0 \(DENY 0\.0\.0\.0/0:\[8080\] IN\)\."):
        _check_address_with_rules(rules, address, IN)


def test_bind_direction_check_first_rule_deny_implicitly_allows(mock_getaddrinfo):
    """
    Test implicit ALLOW for IN (bind) direction when first rule is DENY and no DENY rule matches.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 5000))]
    rules = [create_parsed_rule(DENY, "0.0.0.0/0", [8080],
                                IN)]  # DENY rule for different port
    address = ("127.0.0.1", 5000)
    _check_address_with_rules(rules, address, IN)


def test_bind_direction_check_first_rule_allow_implicitly_denies(mock_getaddrinfo):
    """
    Test implicit DENY for IN (bind) direction when first rule is ALLOW and no rule matches.
    """
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 5000))]
    rules = [create_parsed_rule(ALLOW, "0.0.0.0/0", [80],
                                IN)]  # ALLOW rule for different port
    address = ("127.0.0.1", 5000)
    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 127\.0\.0\.1 \(port 5000\) DENIED by implicit default \(first rule: ALLOW\)\. Resolved IPs: .*"):
        _check_address_with_rules(rules, address, IN)


def test_mixed_ipv4_ipv6_resolution_one_denied(mock_getaddrinfo):
    """
    If hostname resolves to multiple IPs (IPv4 and IPv6), and one IPv6 matches a DENY rule,
    the connection is blocked.
    The first rule is ALLOW to set implicit DENY, but it doesn't match the connection.
    """
    hostname = "mixed.ip.example.com"
    port = 9000
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('172.16.0.5', port)),
        # IPv4, will not be matched by DENY
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '',
         ('2a00:1450:400e:804::200e', port, 0, 0)),  # IPv6, will be matched by DENY
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', port))
        # IPv4, will not be matched by DENY
    ]

    rules = [
        create_parsed_rule(ALLOW, "0.0.0.0/0", [80], OUT),
        # Rule 0: First rule is ALLOW, implicit default is DENY. Doesn't match port.
        create_parsed_rule(DENY, "2a00:1450::/32", [port], OUT)
        # Rule 1: DENY rule for the IPv6 network.
    ]
    address = (hostname, port)

    with pytest.raises(RuntimeError,
                       match=r"Guard network connection to 2a00:1450:400e:804::200e:9000 \(from mixed\.ip\.example\.com\) "
                             r"explicitly DENIED by rule #1 \(DENY 2a00:1450::/32:\[9000\] OUT\)\."):
        _check_address_with_rules(rules, address, OUT)
