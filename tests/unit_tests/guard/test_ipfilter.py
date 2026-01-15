import subprocess
from typing import List

from pysandboxes.guard_socket import parse_rules
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.remote.tools import which_command


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


def test_ip4_filter_conv():
    rules, _ = parse_rules(
        [
            "--net=ALLOW|tcp|localhost|80,443|OUT",
            "--net=ALLOW|tcp|192.0.0.0/8|80,443|OUT",
            "--net=ALLOW|tcp|::1/128|80,443|OUT",  # skip
            "--net=ALLOW|any|::/0|443|OUT",  # skip
            "--net=ALLOW|tcp|0.0.0.0/0|80|IN",
            "--net=ALLOW|any|127.0.0.0/8|*|OUT",
            "--net=ALLOW|any|127.0.0.0/8|80,443|IN",
            "--net=ALLOW|*|127.0.0.0/8|*|OUT",
            "--net=ALLOW|udp|0.0.0.0/0|53|OUT",
            "--net=ALLOW|udp|123.0.0.0/0|12-44|IN",
            "--net=ALLOW|udp|123.0.0.0/32|1,3-5|IN",
            "--net=ALLOW|udp,tcp|192.168.0.1/32|*|IN",
            "--net=ALLOW|any|0.0.0.0/0|80,443|OUT",
            "--net=ALLOW|udp|0.0.0.0/0|53|OUT",
        ])
    ipfilter = rule_to_netfilter(rules, is_ipv6=False)
    print("\n".join(ipfilter))
    status, msg = check_iptables_rules_syntax("\n".join(ipfilter), is_ipv6=False)
    assert status, msg
    assert ['*filter', ':INPUT DROP [0:0]', ':FORWARD DROP [0:0]', ':OUTPUT DROP [0:0]',
            '-A INPUT -p tcp -d 127.0.0.1/32 -m multiport --dports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 127.0.0.1/32 -m multiport --sports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p tcp -d 192.0.0.0/8 -m multiport --dports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 192.0.0.0/8 -m multiport --sports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p tcp -m multiport --sports 80 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -m multiport --dports 80 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -j ACCEPT ',
            '-A INPUT -p tcp -d 127.0.0.0/8 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 127.0.0.0/8 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 80,443 -j ACCEPT ',
            '-A INPUT -p tcp -d 127.0.0.0/8 -m multiport --sports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 127.0.0.0/8 -m multiport --dports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -j ACCEPT ',
            '-A INPUT -p tcp -d 127.0.0.0/8 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 127.0.0.0/8 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 53 -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 12:44  -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 1,3,4,5 -j ACCEPT ',
            '-A INPUT -p tcp -d 192.168.0.1/32 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 192.168.0.1/32 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p udp -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 80,443 -j ACCEPT ',
            '-A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -m multiport --sports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 53 -j ACCEPT ',
            'COMMIT'] == ipfilter


def test_ip6_filter_conv():
    rules, _ = parse_rules(
        [
            "--net=ALLOW|tcp|2001:db8::/32|80,443|OUT",
            "--net=ALLOW|tcp|192.168.0.0/16|80,443|OUT",  # Skip
            "--net=ALLOW|any|0.0.0.0/0|443|OUT",  # Skip
            "--net=ALLOW|tcp|2001:db8::/32|80|IN",
            "--net=ALLOW|any|2001:db8::/32|*|OUT",
            "--net=ALLOW|any|2001:db8::/32|80,443|IN",
            "--net=ALLOW|*|2001:db8::/32|*|OUT",
            "--net=ALLOW|udp|2001:db8::/32|53|OUT",
            "--net=ALLOW|udp|2001:db8::/32|12-44|IN",
            "--net=ALLOW|udp|2001:db8::/32|1,3-5|IN",
            "--net=ALLOW|udp,tcp|2001:db8::/32|*|IN",
            "--net=ALLOW|any|2001:db8::/32|80,443|OUT",
            "--net=ALLOW|udp|2001:db8::/32|53|OUT",
        ])
    ipfilter = rule_to_netfilter(rules, is_ipv6=True)
    print("\n".join(ipfilter))
    status, msg = check_iptables_rules_syntax("\n".join(ipfilter), is_ipv6=True)
    assert status, msg
    assert ['*filter', ':INPUT DROP [0:0]', ':FORWARD DROP [0:0]', ':OUTPUT DROP [0:0]',
            '-A INPUT -p tcp -d 2001:db8::/32 -m multiport --dports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m multiport --sports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m multiport --sports 80 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m multiport --dports 80 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 80,443 -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m multiport --sports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m multiport --dports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 53 -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 12:44  -j ACCEPT ',
            '-A INPUT -p udp -m multiport --sports 1,3,4,5 -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A INPUT -p udp -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 80,443 -j ACCEPT ',
            '-A INPUT -p tcp -d 2001:db8::/32 -m multiport --dports 80,443 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p tcp -d 2001:db8::/32 -m multiport --sports 80,443 -m conntrack --ctstate ESTABLISHED -j ACCEPT ',
            '-A OUTPUT -p udp -m multiport --dports 53 -j ACCEPT ',
            'COMMIT'] == ipfilter
