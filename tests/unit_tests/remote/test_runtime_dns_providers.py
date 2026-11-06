# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` under `bwrap` and `gvisor`: the ruleset, the resolver file and the life of the resolver."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.egress_filter import NameRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.netfilter import runtime_netfilter
from pysandboxes.remote.bwrap_sse_daemon import BWrapSSEDaemon
from pysandboxes.remote.gvisor_bundle import build_oci_spec
from pysandboxes.remote.gvisor_launch import netfilter_rules, runtime_netfilter_rules
from pysandboxes.remote.gvisor_sse_daemon import GVisorSSEDaemon
from pysandboxes.sb_types import ConfigLine

NAMES = (NameRule(True, "example.com", ("tcp",), ((443, 443),)),)
STATIC = SocketRule(
    Action.ALLOW,
    SocketMask((Kind.TCP,), IPv4Network("203.0.113.0/24"), (443,)),
    (Direction.OUT,),
    ConfigLine("net=ALLOW|TCP|203.0.113.0/24|443|OUT", Path("p"), 1),
)
RUNTIME = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES, socket_rules=(STATIC,))
GATEWAY, SLIRP_DNS = IPv4Address("10.0.2.2"), IPv4Address("10.0.2.3")


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def start(self, all_rules: Any) -> int:
        self.calls.append(("start", all_rules))
        return 15353

    def attach(self, pid: int) -> None:
        self.calls.append(("attach", pid))

    def stop(self) -> None:
        self.calls.append(("stop", None))


class TestBwrap:
    def test_a_profile_with_only_name_rules_is_filtered_by_the_network_namespace(self) -> None:
        only_names = EmptyRules._replace(net_resolve="runtime", name_rules=NAMES)

        assert BWrapSSEDaemon._use_network_filtering(only_names) is True
        assert BWrapSSEDaemon._use_network_filtering(EmptyRules) is False

    def test_the_runtime_ruleset_is_the_runtime_builder_with_the_daemon_port_open_before_the_first_commit(self) -> None:
        rules = BWrapSSEDaemon._build_netfilter_rules(RUNTIME, 4242, 15353)

        expected = runtime_netfilter(RUNTIME.socket_rules, 15353, GATEWAY, SLIRP_DNS)
        sse = "-A INPUT -p tcp -s 10.0.2.2/32 --dport 4242 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
        index = expected.index("COMMIT")
        assert list(rules) == [*expected[:index], sse, *expected[index:]]

    def test_runtime_without_the_resolver_port_is_an_error_not_a_silent_pinned_ruleset(self) -> None:
        with pytest.raises(SandBoxError, match="resolver port"):
            BWrapSSEDaemon._build_netfilter_rules(RUNTIME, 4242)

    def test_pinned_ruleset_is_unchanged_and_opens_no_resolver_chain(self) -> None:
        rules = BWrapSSEDaemon._build_netfilter_rules(EmptyRules._replace(socket_rules=(STATIC,)), 4242)

        assert ":LEARNED - [0:0]" not in rules and "*nat" not in rules

    def test_the_guest_resolv_conf_names_the_slirp_dns_in_runtime_only(self, tmp_path: Path) -> None:
        assert BWrapSSEDaemon._runtime_resolv_conf_args(EmptyRules, tmp_path) == []

        args = BWrapSSEDaemon._runtime_resolv_conf_args(RUNTIME, tmp_path)

        assert args[0] == "--ro-bind" and args[2] == str(Path("/etc/resolv.conf").resolve())
        assert Path(args[1]).read_text() == "nameserver 10.0.2.3\n"

    def test_the_hook_of_a_one_shot_run_stops_the_resolver(self) -> None:
        daemon = BWrapSSEDaemon("tok")
        session = FakeSession()
        daemon._dns_session = session  # type: ignore[assignment]

        daemon._kill_slirp()

        assert ("stop", None) in session.calls

    async def test_the_shutdown_of_the_daemon_stops_the_resolver(self) -> None:
        daemon = BWrapSSEDaemon("tok")
        session = FakeSession()
        daemon._dns_session = session  # type: ignore[assignment]

        await daemon._shutdown(graceful_shutdown=False)

        assert ("stop", None) in session.calls


class TestGVisor:
    def test_the_runtime_ruleset_opens_the_daemon_port_in_the_filter_table(self) -> None:
        rules = runtime_netfilter_rules(RUNTIME, 4242, 15353)

        expected = runtime_netfilter(RUNTIME.socket_rules, 15353, GATEWAY, SLIRP_DNS)
        index = expected.index("COMMIT")
        sse = "-A INPUT -p tcp -s 10.0.2.2/32 --dport 4242 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
        assert list(rules) == [*expected[:index], sse, *expected[index:]]
        assert rules.count("COMMIT") == 2

    def test_the_pinned_ruleset_is_still_the_single_table_one(self) -> None:
        assert netfilter_rules(EmptyRules, 4242).count("COMMIT") == 1

    def test_the_resolv_conf_is_bound_over_the_file_the_guest_resolves_in_runtime_only(self, tmp_path: Path) -> None:
        assert GVisorSSEDaemon._runtime_resolv_conf(EmptyRules, tmp_path) == ()

        ((source, destination),) = GVisorSSEDaemon._runtime_resolv_conf(RUNTIME, tmp_path)

        assert destination == str(Path("/etc/resolv.conf").resolve())
        assert Path(source).read_text() == "nameserver 10.0.2.3\n"

    def test_a_file_bind_comes_last_and_read_only(self) -> None:
        spec = build_oci_spec(
            rootfs="/r",
            args=["x"],
            env={},
            mounts_ro=["/etc"],
            mounts_rw=[],
            masks=[("/etc/secret", False)],
            empty_file="/empty",
            cwd="/",
            file_binds=(("/work/resolv.conf", "/etc/resolv.conf"),),
        )

        last = spec["mounts"][-1]
        assert last["source"] == "/work/resolv.conf" and last["destination"] == "/etc/resolv.conf"
        assert "ro" in last["options"]

    def test_the_end_of_a_run_stops_the_resolver_through_kill_slirp(self) -> None:
        daemon = GVisorSSEDaemon("tok")
        session = FakeSession()
        daemon._dns_session = session  # type: ignore[assignment]

        daemon._kill_slirp()

        assert ("stop", None) in session.calls
