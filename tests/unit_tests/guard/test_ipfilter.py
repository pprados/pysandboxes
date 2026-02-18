import subprocess
from pathlib import Path
from typing import List

import pytest

from integration_tests.sb_usage import init_log_level
from pysandboxes.guard_socket import parse_rules
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.remote.tools import which_command
from pysandboxes.sb_types import ConfigLine
from unit_tests.guard.test_guard_io import _deactivate_all_rules, \
    _activate_guard_import_for_tests


@pytest.fixture(autouse=True)
def reset() -> None:
    # Create test files and symlinks
    # It's executer without patch.
    init_log_level()
    _deactivate_all_rules()
    _activate_guard_import_for_tests()


def check_iptables_rules_syntax(rules_content: str, is_ipv6: bool = False) -> tuple[
    bool, str]:
    """
    Checks the syntax of iptables/ip6tables rules without applying them.

    Args:
        rules_content (str): The content of the rules in iptables-save/ip6tables-save format.
        is_ipv6 (bool): True if rules are for IPv6 (ip6tables-restore), False for IPv4 (iptables-restore).

    Returns:
        tuple[bool, str]: A tuple containing (True if syntax is OK, error/success message).
    """
    # Determine the restore command based on IPv4 or IPv6
    restore_command: str = "ip6tables-restore" if is_ipv6 else "iptables-restore"

    # Options for test mode
    command_args: List[str] = [which_command(restore_command), "--test"]

    # Use a temporary file to pass the rules to the restore tool's standard input
    try:
        subprocess.run(
            command_args,
            input=rules_content,
            capture_output=True,
            text=True,
            check=True
        )
        return True, "Rules syntax checked successfully."

    except subprocess.CalledProcessError as e:
        # If the command returns an error, it means the syntax is incorrect
        responses = e.stderr.strip().split("\n")
        if "Permission denied" in responses[-1]:
            responses.pop()
        if not len(responses):
            return True, "Rules syntax checked successfully."
        error_message: str = (f"Syntax error detected:\n"
                              f"{e.stderr.strip()}")
        return False, error_message


def test_ip4_netfilter_conv():
    errors = []
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|tcp|localhost|80,443|OUT", Path(), 0),
            ConfigLine("net=ALLOW|tcp|192.0.0.0/8|80,443|OUT", Path(), 0),
            ConfigLine("net=ALLOW|tcp|::1/128|80,443|OUT", Path(), 0),  # skip
            ConfigLine("net=ALLOW|any|::/0|443|OUT", Path(), 0),  # skip
            ConfigLine("net=ALLOW|tcp|0.0.0.0/0|80|IN", Path(), 0),
            ConfigLine("net=ALLOW|any|127.0.0.0/8|*|OUT", Path(), 0),
            ConfigLine("net=ALLOW|any|127.0.0.0/8|80,443|IN", Path(), 0),
            ConfigLine("net=ALLOW|*|127.0.0.0/8|*|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|0.0.0.0/0|53|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|123.0.0.0/0|12-44|IN", Path(), 0),
            ConfigLine("net=ALLOW|udp|123.0.0.0/32|1,3-5|IN", Path(), 0),
            ConfigLine("net=ALLOW|udp,tcp|192.168.0.1/32|*|IN", Path(), 0),
            ConfigLine("net=ALLOW|any|0.0.0.0/0|80,443|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|0.0.0.0/0|53|OUT", Path(), 0),
            ConfigLine("net=DENY|any|10.0.0.0/8|*|OUT", Path(), 0),
        ], errors)
    ipfilter = rule_to_netfilter(rules, is_ipv6=False)
    status, msg = check_iptables_rules_syntax("\n".join(ipfilter), is_ipv6=False)
    assert status, msg
    assert sorted(
        ['*filter', ':INPUT DROP [0:0]', ':FORWARD DROP [0:0]', ':OUTPUT DROP [0:0]',
         '-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
         '-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 10.0.0.0/8  -j REJECT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 127.0.0.0/8  -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -s 192.168.0.1/32  -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -m multiport --sports 80,443 -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -s 127.0.0.0/8  -m multiport --dports 80,443 -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 127.0.0.1/32  -m multiport --sports 80,443 -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 192.0.0.0/8  -m multiport --sports 80,443 -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -m multiport --dports 80 -j ACCEPT',
         'COMMIT']
    ) == sorted(ipfilter)


def test_ip6_netfilter_conv():
    errors = []
    rules, _ = parse_rules(
        [
            ConfigLine("net=ALLOW|tcp|2001:db8::/32|80,443|OUT", Path(), 0),
            ConfigLine("net=ALLOW|tcp|192.168.0.0/16|80,443|OUT", Path(), 0),  # Skip,
            ConfigLine("net=ALLOW|any|0.0.0.0/0|443|OUT", Path(), 0),  # Skip
            ConfigLine("net=ALLOW|tcp|2001:db8::/32|80|IN", Path(), 0),
            ConfigLine("net=ALLOW|any|2001:db8::/32|*|OUT", Path(), 0),
            ConfigLine("net=ALLOW|any|2001:db8::/32|80,443|IN", Path(), 0),
            ConfigLine("net=ALLOW|*|2001:db8::/32|*|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|2001:db8::/32|53|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|2001:db8::/32|12-44|IN", Path(), 0),
            ConfigLine("net=ALLOW|udp|2001:db8::/32|1,3-5|IN", Path(), 0),
            ConfigLine("net=ALLOW|udp,tcp|2001:db8::/32|*|IN", Path(), 0),
            ConfigLine("net=ALLOW|any|2001:db8::/32|80,443|OUT", Path(), 0),
            ConfigLine("net=ALLOW|udp|2001:db8::/32|53|OUT", Path(), 0),
            ConfigLine("net=DENY|any|10.0.0.0/8|*|OUT", Path(), 0),
        ], errors)
    ipfilter = rule_to_netfilter(rules, is_ipv6=True)
    status, msg = check_iptables_rules_syntax("\n".join(ipfilter), is_ipv6=True)
    assert status, msg
    assert sorted(
        ['*filter', ':INPUT DROP [0:0]', ':FORWARD DROP [0:0]', ':OUTPUT DROP [0:0]',
         '-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
         '-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 2001:db8::/32  -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -s 2001:db8::/32  -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -s 2001:db8::/32  -m multiport --dports 80,443 -j ACCEPT',
         '-A OUTPUT -p tcp -m conntrack --ctstate NEW -d 2001:db8::/32  -m multiport --sports 80,443 -j ACCEPT',
         '-A INPUT -p tcp -m conntrack --ctstate NEW,ESTABLISHED -s 2001:db8::/32  -m multiport --dports 80 -j ACCEPT',
         'COMMIT']
    ) == sorted(ipfilter)
