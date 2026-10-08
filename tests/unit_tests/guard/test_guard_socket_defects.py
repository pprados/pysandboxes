# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Network guard defects: each test fails on the code before its fix.

Only local addresses are reached: the loopback and sockets the test opens itself.
"""

import socket
import sys
from collections.abc import Iterator
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from pathlib import Path
from socket import AddressFamily, SocketKind
from typing import Any
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

import pysandboxes.guard_files as gf
import pysandboxes.guard_socket as gs
from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.e import SandBoxError, sandbox_denials
from pysandboxes.guard_socket import (
    Direction,
    Kind,
    SocketRules,
    _addr_infos_from_ips,
    _check_address_with_rules,
    _deactivate_guard_sockets,
    activate_guard,
    generate_rules,
    parse_rules,
    patch_rules,
)
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.sb_types import ConfigLine


class _FakeSocket:
    """Stand-in for a socket object: the wrappers read ``type`` and ``family``."""

    def __init__(self, kind: SocketKind, family: AddressFamily = AddressFamily.AF_INET) -> None:
        self.type = kind
        self.family = family


def _parse(*rules: str) -> SocketRules:
    errors: list[ErrorMsg] = []
    socket_rules, _, _ = parse_rules([ConfigLine(rule, Path(), ln) for ln, rule in enumerate(rules)], errors)
    assert not errors
    return socket_rules


def _arm(*rules: str) -> None:
    activate_guard(_parse(*rules))


@pytest.fixture
def udp_receiver() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(0.5)
        yield receiver


@pytest.fixture
def tcp_listener() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield listener


@pytest.fixture
def learning_mode(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    captured: list[Any] = []
    monkeypatch.setattr(gs, "is_learning_mode", lambda: True)
    monkeypatch.setattr(gs, "add_learning_rule", captured.append)
    return captured


@pytest.fixture
def pin_dns_reset() -> Iterator[None]:
    saved = gs._pin_dns
    yield
    gs._pin_dns = saved


# %% 1. A send that carries an address


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="no sendmsg on this platform")
def test_udp_sendmsg_to_an_address_no_rule_allows_is_refused(udp_receiver: socket.socket) -> None:
    _arm("net=ALLOW|UDP|127.0.0.1|1|OUT")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        with pytest.raises(RuleSocketConnectionRefusedError):
            sender.sendmsg([b"x"], [], 0, udp_receiver.getsockname())


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="no sendmsg on this platform")
def test_udp_sendmsg_to_an_allowed_address_reaches_it(udp_receiver: socket.socket) -> None:
    port = udp_receiver.getsockname()[1]
    _arm(f"net=ALLOW|UDP|127.0.0.1|{port}|OUT")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendmsg([b"x"], [], 0, ("127.0.0.1", port))
    assert udp_receiver.recv(1) == b"x"


@pytest.mark.skipif(not hasattr(socket, "MSG_FASTOPEN"), reason="no TCP fast open on this platform")
def test_tcp_sendto_with_fast_open_is_judged_as_a_connect(tcp_listener: socket.socket) -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|1|OUT")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.5)
        with pytest.raises(RuleSocketConnectionRefusedError):
            client.sendto(b"x", socket.MSG_FASTOPEN, tcp_listener.getsockname())


# %% 2. IPv4-mapped IPv6 addresses


def test_ipv4_mapped_address_is_judged_by_the_ipv4_rules() -> None:
    rules = _parse("net=ALLOW|*|*|*|OUT", "net=DENY|*|127.0.0.1/32|*|OUT")
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_address_with_rules(rules, Kind.TCP, ("::ffff:127.0.0.1", 80), Direction.OUT)


# %% 3. listen() without bind()


def test_listen_without_bind_is_judged_as_a_wildcard_bind() -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|*|IN")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        with pytest.raises(RuleSocketConnectionRefusedError):
            server.listen()


def test_listen_after_an_allowed_bind_is_not_judged_again() -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|*|IN")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()


def test_listen_without_bind_passes_with_a_wildcard_rule() -> None:
    _arm("net=ALLOW|TCP|0.0.0.0/32|0|IN")
    listen = patch_rules(learn=False)["socket.socket.listen"](lambda *_: None)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:  # never bound: nothing listens
        listen(server)


# %% 4. AF_UNIX connect needs write access


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no AF_UNIX")
def test_unix_connect_needs_write_access_to_the_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = str(tmp_path / "s")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        errors: list[ErrorMsg] = []
        file_rules, _ = gf.parse_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 1)], errors)
        assert not errors
        monkeypatch.setattr(gf, "_rules", file_rules)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            # The file guard refuses it, naming the read-only rule.
            with pytest.raises(SandBoxError) as refused:
                client.connect(path)
            assert sandbox_denials(refused.value)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no AF_UNIX")
def test_unix_connect_passes_with_write_access(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = str(tmp_path / "s")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        errors: list[ErrorMsg] = []
        file_rules, _ = gf.parse_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 1)], errors)
        assert not errors
        monkeypatch.setattr(gf, "_rules", file_rules)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)


@pytest.mark.skipif(sys.platform != "linux", reason="abstract AF_UNIX addresses are a Linux-only namespace")
def test_connect_to_an_abstract_unix_address_is_refused_not_crashed() -> None:
    # G13: an abstract address has no filesystem path, so file rules cannot judge it.
    # It must be refused with the guard's socket refusal, not crash in os.path.realpath.
    _arm()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        with pytest.raises(RuleSocketConnectionRefusedError):
            client.connect("\x00pysandboxes-test-abstract")


@pytest.mark.skipif(sys.platform != "linux", reason="abstract AF_UNIX addresses are a Linux-only namespace")
def test_sendto_an_abstract_unix_address_is_refused_not_crashed() -> None:
    _arm()
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
        with pytest.raises(RuleSocketConnectionRefusedError):
            sender.sendto(b"x", "\x00pysandboxes-test-abstract")


# %% 5. Name resolution


def _resolves_to(*ips: str) -> list[Any]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


def test_connect_uses_the_address_that_was_checked() -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|8080|OUT")
    calls: list[Any] = []
    wrapped = patch_rules(learn=False)["socket.socket.connect"](lambda _self, address: calls.append(address))
    with patch("pysandboxes.guard_socket.getaddrinfo", return_value=_resolves_to("127.0.0.1")):
        wrapped(_FakeSocket(SocketKind.SOCK_STREAM), ("svc.test", 8080))
    assert calls == [("127.0.0.1", 8080)]


def test_a_name_with_one_denied_address_is_refused() -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|8080|OUT")
    wrapped = patch_rules(learn=False)["socket.socket.connect"](lambda *_: None)
    with patch("pysandboxes.guard_socket.getaddrinfo", return_value=_resolves_to("127.0.0.1", "127.0.0.2")):
        with pytest.raises(RuleSocketConnectionRefusedError):
            wrapped(_FakeSocket(SocketKind.SOCK_STREAM), ("svc.test", 8080))


def test_resolution_cache_does_not_outlive_an_activation() -> None:
    with patch.object(socket, "getaddrinfo", return_value=_resolves_to("127.0.0.1")):
        gs.getaddrinfo("cache.test", 0)
    assert gs.getaddrinfo.cache_info().currsize
    activate_guard(())
    assert not gs.getaddrinfo.cache_info().currsize


def test_deactivation_resets_the_cache_and_the_pinned_names(pin_dns_reset: None) -> None:
    gs._pin_dns = ImmutableDict({"pinned.test": tuple(_addr_infos_from_ips([ip_address("127.0.0.1")]))})
    with patch.object(socket, "getaddrinfo", return_value=_resolves_to("127.0.0.1")):
        gs.getaddrinfo("cache.test", 0)
    _deactivate_guard_sockets()
    assert not gs.getaddrinfo.cache_info().currsize
    assert not gs._pin_dns


# %% 6. One rule, one meaning, in both layers

_CROSS_RULES = (
    "net=ALLOW|TCP|10.1.1.1||OUT",
    "net=ALLOW|TCP|127.0.0.1/32|8000|IN",
    "net=ALLOW|TCP|0.0.0.0/32|9000|IN",
    "net=ALLOW|UDP|10.2.0.0/16|53,123|OUT",
    "net=DENY|TCP|10.3.3.3/32|443|OUT",
    "net=ALLOW|TCP|10.3.0.0/16|443|OUT",
    "net=ALLOW|TCP|10.4.4.4|" + ",".join(str(p) for p in range(1, 21)) + "|OUT",
)

# (direction, kind, address, port): the local address for IN, as bind() names it; the remote one for OUT.
_PROBES = (
    (Direction.OUT, Kind.TCP, "10.1.1.1", 80),
    (Direction.IN, Kind.TCP, "127.0.0.1", 8000),
    (Direction.IN, Kind.TCP, "127.0.0.1", 8001),
    (Direction.IN, Kind.TCP, "0.0.0.0", 9000),
    (Direction.OUT, Kind.UDP, "10.2.5.5", 123),
    (Direction.OUT, Kind.UDP, "10.2.5.5", 124),
    (Direction.OUT, Kind.TCP, "10.3.3.3", 443),
    (Direction.OUT, Kind.TCP, "10.3.4.4", 443),
    (Direction.OUT, Kind.TCP, "10.4.4.4", 17),
    (Direction.OUT, Kind.TCP, "10.4.4.4", 21),
)

_REMOTE_PEER = "192.0.2.10"  # the source of an incoming packet: a rule naming the local address must not test it
_LOCAL_ADDRESS = "10.0.2.15"  # the source of an outgoing packet


def _netfilter_verdict(lines: list[str], direction: Direction, kind: Kind, address: str, port: int) -> bool:
    """First-match evaluation of the generated lines for a new connection; the chains drop by default."""
    chain = "INPUT" if direction == Direction.IN else "OUTPUT"
    src = _REMOTE_PEER if direction == Direction.IN else _LOCAL_ADDRESS
    dst = address
    for line in lines:
        tokens = line.split()
        if tokens[:2] != ["-A", chain] or "-p" not in tokens:
            continue
        options = dict(zip(tokens[2:-1], tokens[3:], strict=True))
        if options["-p"] != kind.name.lower():
            continue
        if "-s" in options and ip_address(src) not in ip_network(options["-s"]):
            continue
        if "-d" in options and ip_address(dst) not in ip_network(options["-d"]):
            continue
        if "--dports" in options:
            ports: set[int] = set()
            for item in options["--dports"].split(","):
                low, _, high = item.partition(":")
                ports.update(range(int(low), int(high or low) + 1))
            if port not in ports:
                continue
        return options["-j"] == "ACCEPT"
    return False


def _python_verdict(rules: SocketRules, direction: Direction, kind: Kind, address: str, port: int) -> bool:
    try:
        _check_address_with_rules(rules, kind, (address, port), direction, log=False)
        return True
    except RuleSocketConnectionRefusedError:
        return False


def test_the_python_layer_and_iptables_agree_on_the_same_rules() -> None:
    rules = _parse(*_CROSS_RULES)
    lines = rule_to_netfilter(rules, [], is_ipv6=False)
    disagreements = [probe for probe in _PROBES if _python_verdict(rules, *probe) != _netfilter_verdict(lines, *probe)]
    assert not disagreements, "\n".join(lines)


def test_a_port_list_is_split_at_the_multiport_limit() -> None:
    lines = rule_to_netfilter(_parse(_CROSS_RULES[-1]), [], is_ipv6=False)
    dports = [line.split("--dports ")[1].split()[0] for line in lines if "--dports" in line]
    assert dports and all(len(item.split(",")) <= 15 for item in dports)
    assert sorted(int(p) for item in dports for p in item.split(",")) == list(range(1, 21))


def test_a_dns_server_is_written_with_its_own_prefix_in_its_own_table() -> None:
    dns: list[Any] = [IPv4Address("10.0.2.3"), IPv6Address("fd00::3")]
    v4 = "\n".join(rule_to_netfilter((), dns, is_ipv6=False))
    v6 = "\n".join(rule_to_netfilter((), dns, is_ipv6=True))
    assert "-d 10.0.2.3/32 " in v4 and "fd00::3" not in v4
    assert "-d fd00::3/128 " in v6 and "10.0.2.3" not in v6


# %% 7. Learning and resolution edge cases


def test_a_learned_wildcard_bind_generates_a_rule(learning_mode: list[Any]) -> None:
    _arm("net=ALLOW|TCP|10.0.0.1|1|IN")
    wrapped = patch_rules(learn=False)["socket.socket.bind"](lambda *_: None)
    wrapped(_FakeSocket(SocketKind.SOCK_STREAM), ("", 8000))
    assert "net=ALLOW|TCP|0.0.0.0/32|8000|IN" in generate_rules(set(learning_mode))


def test_pinned_getaddrinfo_accepts_a_service_name(pin_dns_reset: None) -> None:
    gs._pin_dns = ImmutableDict({"svc.test": tuple(_addr_infos_from_ips([ip_address("127.0.0.1")]))})
    resolve = gs._wrap_socket_getaddrinfo(lambda *_: [])
    result = resolve("svc.test", "http", 0, socket.SOCK_STREAM)
    assert result and {info[4][1] for info in result} == {80}


def test_a_pinned_name_without_ipv4_reports_eai_again(pin_dns_reset: None) -> None:
    gs._pin_dns = ImmutableDict({"v6.test": tuple(_addr_infos_from_ips([ip_address("::1")]))})
    resolve = gs._wrap_socket_gethostbyname(lambda *_: "unreachable")
    with pytest.raises(socket.gaierror) as raised:
        resolve("v6.test")
    assert raised.value.errno == socket.EAI_AGAIN
