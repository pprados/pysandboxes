# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The channel from the host to the firewall of a VM guest: what the guest runs, and what it refuses."""

import inspect
import json
import socket
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.egress_filter import NameRule
from pysandboxes.remote import guest_learned as gl
from pysandboxes.remote.netns_enforcer import NetnsIptablesEnforcer
from pysandboxes.remote.runtime_dns import RuntimeDnsSession

TOKEN = "s3cret"
ADD = ["-A", "LEARNED", "-d", "10.0.2.2", "-p", "tcp", "--dport", "443", "-j", "ACCEPT"]


def _line(argv: Any, token: str = TOKEN) -> bytes:
    return json.dumps({"token": token, "argv": argv}).encode() + b"\n"


def _handle(line: bytes, ran: list[list[str]], rc: int = 0) -> int:
    def run(argv: list[str]) -> int:
        ran.append(argv)
        return rc

    return gl.handle(line, TOKEN, "/usr/sbin/iptables-nft", run)


def test_an_add_in_the_learned_chain_runs_with_the_iptables_of_the_guest() -> None:
    ran: list[list[str]] = []

    assert _handle(_line(ADD), ran) == 0
    assert ran == [["/usr/sbin/iptables-nft", *ADD]]


def test_a_delete_in_the_learned_chain_is_run_too() -> None:
    ran: list[list[str]] = []

    assert _handle(_line(["-D", *ADD[1:]]), ran) == 0 and len(ran) == 1


def test_the_return_code_of_iptables_is_the_answer() -> None:
    assert _handle(_line(ADD), [], rc=4) == 4


@pytest.mark.parametrize(
    "argv",
    [
        ["-F", "LEARNED"],
        ["-A", "OUTPUT", "-j", "ACCEPT"],
        ["-P", "OUTPUT", "ACCEPT"],
        ["-t", "nat", "-A", "LEARNED"],
        ["-A", "LEARNED"],
        "-A LEARNED -j ACCEPT",
        ["-A", "LEARNED", 5, "x"],
    ],
)
def test_nothing_but_an_add_or_a_delete_in_the_learned_chain_is_run(argv: Any) -> None:
    ran: list[list[str]] = []

    assert _handle(_line(argv), ran) == 1
    assert ran == []


def test_a_wrong_token_runs_nothing() -> None:
    ran: list[list[str]] = []

    assert _handle(_line(ADD, token="guess"), ran) == 1
    assert ran == []


@pytest.mark.parametrize("raw", [b"", b"not json\n", b"{}\n", b'{"token": "s3cret"}\n', b"[1]\n"])
def test_a_malformed_request_runs_nothing(raw: bytes) -> None:
    ran: list[list[str]] = []

    assert _handle(raw, ran) == 1
    assert ran == []


def test_a_request_sent_over_a_socket_reaches_the_server_and_its_answer_comes_back() -> None:
    ran: list[list[str]] = []

    def run(argv: list[str]) -> int:
        ran.append(argv)
        return 0

    server = gl.serve(0, TOKEN, "/ipt", run, host="127.0.0.1")
    port = server.getsockname()[1]
    try:
        assert gl.send(port, TOKEN, ADD) == 0
        assert gl.send(port, "wrong", ADD) == 1
    finally:
        server.close()

    assert ran == [["/ipt", *ADD]]


def test_a_guest_that_cannot_be_reached_answers_failure_not_an_exception() -> None:
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]

    assert gl.send(port, TOKEN, ADD) == 1


def test_the_helper_listens_when_it_is_started() -> None:
    # The program of the sandbox resolves a name at once: a helper still importing would refuse the host's request.
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]

    helper = gl.start_helper(port, TOKEN, "/ipt", host="127.0.0.1")
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    finally:
        assert helper.stdin is not None
        helper.stdin.close()
        helper.wait(timeout=10)


def test_the_default_host_is_not_every_interface() -> None:
    """``serve()`` must not default to ``0.0.0.0`` (every guest interface).

    Only the guest's user-mode-network address actually receives a connection QEMU's
    hostfwd forwards (its loopback does not: an empty guest address in
    ``hostfwd=tcp:127.0.0.1:P-:P`` targets the guest's NIC, not ``127.0.0.1`` inside it).
    """
    default = inspect.signature(gl.serve).parameters["host"].default

    assert default not in ("0.0.0.0", "127.0.0.1")
    assert default == gl.GUEST_USER_NET_ADDRESS


def test_serve_binds_only_the_given_address_not_every_interface() -> None:
    """A real bind to one loopback alias must refuse a connection aimed at a different one.

    Proves the narrowing itself works (the old default, 0.0.0.0, would have accepted both).
    The real QEMU hostfwd path (host 127.0.0.1 -> guest's user-net address) is not exercised
    here -- no VM is started by this test.
    """
    server = gl.serve(0, TOKEN, "/ipt", host="127.0.0.2")
    port = server.getsockname()[1]
    try:
        assert server.getsockname()[0] == "127.0.0.2"
        socket.create_connection(("127.0.0.2", port), timeout=1).close()
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)
    finally:
        server.close()


def test_the_helpers_host_override_reaches_the_real_subprocess() -> None:
    """``start_helper``'s host override plumbs through the CLI to the real ``serve()`` call.

    Same narrowing proof as above, through the actual subprocess entry point ``main()`` uses
    in the guest, rather than calling ``serve()`` directly.
    """
    with socket.socket() as free:
        free.bind(("127.0.0.2", 0))
        port = free.getsockname()[1]

    helper = gl.start_helper(port, TOKEN, "/ipt", host="127.0.0.2")
    try:
        socket.create_connection(("127.0.0.2", port), timeout=1).close()
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)
    finally:
        assert helper.stdin is not None
        helper.stdin.close()
        helper.wait(timeout=10)


def test_the_guest_enforcer_opens_each_port_of_a_name_rule_through_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []

    def send(port: int, token: str, argv: list[str]) -> int:
        sent.append(argv)
        return 0

    monkeypatch.setattr(gl, "send", send)

    NetnsIptablesEnforcer.via_guest(4242, TOKEN).allow(
        __import__("ipaddress").ip_address("10.0.2.2"), NameRule(True, "a.test", ("tcp",), ((443, 443),)), 60
    )

    assert sent == [["-A", "LEARNED", "-d", "10.0.2.2", "-p", "tcp", "--dport", "443", "-j", "ACCEPT"]]


def test_a_session_attached_to_a_guest_gives_the_resolver_the_guest_enforcer(monkeypatch: pytest.MonkeyPatch) -> None:
    attached: list[Any] = []

    class FakeDns:
        def attach(self, enforcer: Any) -> None:
            attached.append(enforcer)

    session = RuntimeDnsSession(join="guest")
    session._dns = FakeDns()  # type: ignore[assignment]

    session.attach_guest(4242, TOKEN)

    assert len(attached) == 1 and attached[0]._prefix == []


def test_a_guest_session_needs_no_tool_of_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysandboxes.all_rules import EmptyRules
    from pysandboxes.remote import runtime_dns as rd

    class FakeDns:
        def __init__(self, *_: Any, **__: Any) -> None: ...

        def start(self) -> int:
            return 15353

    monkeypatch.setattr(rd, "RuntimeDns", FakeDns)
    monkeypatch.setattr(rd, "which_command", lambda name: None)
    monkeypatch.setattr(rd, "get_upstream_dns", lambda: [__import__("ipaddress").IPv4Address("198.51.100.53")])
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=(NameRule(True, "a.test", ("tcp",), ()),))

    assert RuntimeDnsSession(join="guest").start(rules) == 15353
