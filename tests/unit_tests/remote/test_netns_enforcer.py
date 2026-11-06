# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from ipaddress import ip_address

import pytest
from pysandboxes.remote.netns_enforcer import NetnsIptablesEnforcer

from pysandboxes.egress_filter import NameRule

PREFIX = ["/usr/bin/nsenter", "-t", "4242", "-U", "-n", "--preserve-credentials", "/usr/sbin/iptables"]


class Recorder:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return 1 if self.fail_on == len(self.calls) else 0


def enforcer(run: Recorder) -> NetnsIptablesEnforcer:
    return NetnsIptablesEnforcer(4242, "/usr/bin/nsenter", "/usr/sbin/iptables", run)


def test_allow_appends_one_rule_per_protocol_and_port_range() -> None:
    run = Recorder()
    rule = NameRule(True, "example.com", ("tcp", "udp"), ((443, 443), (8000, 8010)))
    enforcer(run).allow(ip_address("192.0.2.7"), rule, 300)
    assert run.calls == [
        PREFIX + ["-A", "LEARNED", "-d", "192.0.2.7", "-p", "tcp", "--dport", "443", "-j", "ACCEPT"],
        PREFIX + ["-A", "LEARNED", "-d", "192.0.2.7", "-p", "tcp", "--dport", "8000:8010", "-j", "ACCEPT"],
        PREFIX + ["-A", "LEARNED", "-d", "192.0.2.7", "-p", "udp", "--dport", "443", "-j", "ACCEPT"],
        PREFIX + ["-A", "LEARNED", "-d", "192.0.2.7", "-p", "udp", "--dport", "8000:8010", "-j", "ACCEPT"],
    ]


def test_a_rule_without_ports_opens_every_port() -> None:
    run = Recorder()
    enforcer(run).allow(ip_address("192.0.2.7"), NameRule(True, "example.com", ("tcp",)), 300)
    assert run.calls == [PREFIX + ["-A", "LEARNED", "-d", "192.0.2.7", "-p", "tcp", "-j", "ACCEPT"]]


def test_revoke_deletes_the_same_rules() -> None:
    allow, revoke = Recorder(), Recorder()
    rule = NameRule(True, "example.com", ("tcp",), ((443, 443),))
    enforcer(allow).allow(ip_address("192.0.2.7"), rule, 300)
    enforcer(revoke).revoke(ip_address("192.0.2.7"), rule)
    assert revoke.calls == [[*c[: len(PREFIX)], "-D", *c[len(PREFIX) + 1 :]] for c in allow.calls]


def test_allow_is_not_deduplicated_so_two_rules_do_not_revoke_each_other() -> None:
    run = Recorder()
    first = NameRule(True, "example.com", ("tcp",), ((443, 443),))
    second = NameRule(True, "api.example.com", ("tcp",), ((443, 443),))
    enforcer(run).allow(ip_address("192.0.2.7"), first, 300)
    enforcer(run).allow(ip_address("192.0.2.7"), second, 300)
    assert len(run.calls) == 2 and run.calls[0] == run.calls[1]
    assert all("-C" not in call for call in run.calls)


def test_a_failed_append_raises_and_rolls_back_the_ones_already_added() -> None:
    run = Recorder(fail_on=2)
    rule = NameRule(True, "example.com", ("tcp", "udp"), ((443, 443),))
    with pytest.raises(OSError, match="iptables"):
        enforcer(run).allow(ip_address("192.0.2.7"), rule, 300)
    assert run.calls[0][len(PREFIX)] == "-A" and run.calls[2][len(PREFIX)] == "-D"
    assert run.calls[2][len(PREFIX) + 1 :] == run.calls[0][len(PREFIX) + 1 :]


def test_a_failed_delete_raises_after_trying_every_rule() -> None:
    run = Recorder(fail_on=1)
    rule = NameRule(True, "example.com", ("tcp", "udp"), ((443, 443),))
    with pytest.raises(OSError, match="iptables"):
        enforcer(run).revoke(ip_address("192.0.2.7"), rule)
    assert len(run.calls) == 2


def test_ipv6_is_skipped_because_the_sandbox_has_no_ipv6_route() -> None:
    run = Recorder()
    enforcer(run).allow(ip_address("2001:db8::1"), NameRule(True, "example.com"), 300)
    enforcer(run).revoke(ip_address("2001:db8::1"), NameRule(True, "example.com"))
    assert run.calls == []
