# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Coverage-focused unit tests for ``pysandboxes.guard_socket``.

These target lines the existing ``test_guard_socket*.py`` files leave unexercised:
the learning-mode bookkeeping on bind/connect/connect_ex/sendto/the resolvers, the
AF_UNIX branches of the socket wrappers, the debug-logging branch of
``_check_address_with_rules``, ``set_pin_dns``/``apply_pin_dns_resolution``,
``_read_host_file``'s platform branches, and ``generate_rules``'s aliasing and
duplicate-rule paths.
"""

import logging
import re
import socket
import sys
from collections.abc import Callable, Iterator
from ipaddress import ip_address
from pathlib import Path
from socket import AddressFamily, SocketKind
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest  # type: ignore[import-untyped]

import pysandboxes.guard_files as gf
import pysandboxes.guard_socket as gs
from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.guard_socket import (
    AddrInfoType,
    Direction,
    Kind,
    LearnSocketRule,
    _check_address_with_rules,
    _convert_ports_range,
    _flatten_ports,
    _is_loopback,
    activate_guard,
    generate_rules,
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


@pytest.fixture
def learning_mode(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Force learning mode and capture every rule handed to ``add_learning_rule``."""
    captured: list[Any] = []
    monkeypatch.setattr(gs, "is_learning_mode", lambda: True)
    monkeypatch.setattr(gs, "add_learning_rule", captured.append)
    return captured


@pytest.fixture
def pin_dns_reset() -> Iterator[None]:
    """Restore the pinned resolution table a test may have replaced."""
    saved = gs._pin_dns
    yield
    gs._pin_dns = saved


class _FakeSocket:
    """Stand-in for a socket object: the wrappers read ``type`` and ``family``."""

    def __init__(self, kind: SocketKind, family: AddressFamily = AddressFamily.AF_INET) -> None:
        self.type = kind
        self.family = family


def _arm(*rules: str) -> None:
    """Arm the socket guard with the given ``net=`` rules."""
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(rule, Path(), ln) for ln, rule in enumerate(rules)]
    socket_rules, _, _ = parse_rules(lines, errors)
    assert not errors
    activate_guard(socket_rules)


def _guarded(qualname: str) -> Callable[..., Any]:
    """Build the wrapper the patch table would install."""
    return patch_rules(learn=False)[qualname](lambda *a, **k: "called")


# %% _convert_ports_range / _flatten_ports defensive branches


def test_convert_ports_range_rejects_a_start_port_out_of_range() -> None:
    with pytest.raises(
        ValueError,
        match=re.escape("Start port 70000 in range '70000-70001' is out of valid range (0-65535)."),
    ):
        _convert_ports_range("70000-70001")


def test_flatten_ports_rejects_an_unsupported_element_type() -> None:
    """_convert_ports_range only ever builds a set of int or range: this asserts that a
    third type reaching _flatten_ports directly is refused rather than silently ignored."""
    with pytest.raises(AssertionError, match="Type not supported"):
        _flatten_ports({"not-a-port"})  # type: ignore[arg-type]


# %% Small standalone helpers


def test_is_loopback_returns_false_for_a_name_that_is_not_an_ip() -> None:
    assert _is_loopback("not-an-ip-address") is False


# %% pin_dns installation


def test_set_pin_dns_installs_the_table_and_refuses_a_second_call(pin_dns_reset: None) -> None:
    gs._pin_dns = cast(ImmutableDict[str, tuple[AddrInfoType, ...]], ImmutableDict({}))
    entries = cast(
        ImmutableDict[str, tuple[AddrInfoType, ...]],
        ImmutableDict({"pinned.example": ((socket.AF_INET, SocketKind.SOCK_STREAM, 6, "", ("198.51.100.7", 0)),)}),
    )

    gs.set_pin_dns(entries)

    assert gs._pin_dns == entries
    with pytest.raises(AssertionError):
        gs.set_pin_dns(entries)


def test_apply_pin_dns_resolution_is_a_noop_without_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gs, "_pin_dns", cast(ImmutableDict[str, tuple[AddrInfoType, ...]], ImmutableDict({})))
    original = object()
    fake_module = SimpleNamespace(gethostbyname=original)

    gs.apply_pin_dns_resolution(fake_module)

    assert fake_module.gethostbyname is original


def test_apply_pin_dns_resolution_wraps_the_resolvers_when_pins_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proving the wrap actually happened, not merely that the attribute changed:
    the wrapped resolver must answer from the pin instead of the underlying one."""
    monkeypatch.setattr(
        gs,
        "_pin_dns",
        cast(
            ImmutableDict[str, tuple[AddrInfoType, ...]],
            ImmutableDict({"pinned.example": ((socket.AF_INET, SocketKind.SOCK_STREAM, 6, "", ("198.51.100.7", 0)),)}),
        ),
    )
    fake_module = SimpleNamespace(
        gethostbyname=lambda *a, **k: "should-not-be-reached",
        gethostbyname_ex=lambda *a, **k: "orig",
        getaddrinfo=lambda *a, **k: "orig",
    )

    gs.apply_pin_dns_resolution(fake_module)

    assert fake_module.gethostbyname("pinned.example") == "198.51.100.7"


# %% Resolver fallback and learning-mode branches


def test_gethostbyname_falls_back_to_a_v4_string_found_later_in_the_pin(pin_dns_reset: None) -> None:
    """The first loop only matches AF_INET entries; the second loop re-parses each
    pinned address and must both skip an unparsable one and return a v4 match found
    later in the list, instead of raising straight away."""
    gs._pin_dns = cast(
        ImmutableDict[str, tuple[AddrInfoType, ...]],
        ImmutableDict(
            {
                "mixed.example": (
                    (socket.AF_INET6, SocketKind.SOCK_STREAM, 6, "", ("not-an-address", 0)),
                    (socket.AF_INET6, SocketKind.SOCK_STREAM, 6, "", ("10.0.0.9", 0)),
                )
            }
        ),
    )
    wrapped = patch_rules(learn=False)["socket.gethostbyname"](lambda *a, **k: "203.0.113.1")

    assert wrapped("mixed.example") == "10.0.0.9"


def test_gethostbyname_learns_the_resolved_address(learning_mode: list[Any]) -> None:
    wrapped = patch_rules(learn=False)["socket.gethostbyname"](lambda name, *a, **k: "5.6.7.8")

    assert wrapped("learn.example") == "5.6.7.8"
    assert learning_mode == [
        LearnSocketRule("gethostbyname", Kind.UNKNOWN, "learn.example", 0, Direction.OUT, (ip_address("5.6.7.8"),))
    ]


def test_gethostbyname_ex_learns_all_resolved_addresses(learning_mode: list[Any]) -> None:
    wrapped = patch_rules(learn=False)["socket.gethostbyname_ex"](
        lambda name, *a, **k: (name, [], ["5.6.7.8", "9.10.11.12"])
    )

    result = wrapped("learn.example")

    assert result == ("learn.example", [], ["5.6.7.8", "9.10.11.12"])
    assert learning_mode == [
        LearnSocketRule(
            "gethostbyname_ex",
            Kind.UNKNOWN,
            "learn.example",
            0,
            Direction.OUT,
            (ip_address("5.6.7.8"), ip_address("9.10.11.12")),
        )
    ]


def test_getaddrinfo_learns_the_resolved_addresses(learning_mode: list[Any]) -> None:
    fake_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("5.6.7.8", 443))]
    wrapped = patch_rules(learn=False)["socket.getaddrinfo"](lambda *a, **k: fake_result)

    result = wrapped("learn.example", 443)

    assert result == fake_result
    assert learning_mode == [
        LearnSocketRule("getaddrinfo", Kind.UNKNOWN, "learn.example", 443, Direction.OUT, (ip_address("5.6.7.8"),))
    ]


def test_bind_records_a_learning_rule_instead_of_raising_when_refused(learning_mode: list[Any]) -> None:
    _arm("net=ALLOW|TCP|10.0.0.1|1|IN")
    wrapped = patch_rules(learn=False)["socket.socket.bind"](lambda *a, **k: None)
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    wrapped(sock, ("127.0.0.1", 9999))  # refused by the armed rule, but learning mode swallows it

    assert learning_mode == [LearnSocketRule("bind", Kind.TCP, "127.0.0.1", 9999, Direction.IN, ())]


def test_connect_records_a_learning_rule_instead_of_raising_when_refused(learning_mode: list[Any]) -> None:
    _arm("net=ALLOW|TCP|10.0.0.1|1|OUT")
    wrapped = patch_rules(learn=False)["socket.socket.connect"](lambda *a, **k: None)
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    wrapped(sock, ("127.0.0.1", 9999))

    assert learning_mode == [LearnSocketRule("connect", Kind.TCP, "127.0.0.1", 9999, Direction.OUT, ())]


def test_connect_ex_records_a_learning_rule_instead_of_raising_when_refused(learning_mode: list[Any]) -> None:
    _arm("net=ALLOW|TCP|10.0.0.1|1|OUT")
    wrapped = patch_rules(learn=False)["socket.socket.connect_ex"](lambda *a, **k: 0)
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    wrapped(sock, ("127.0.0.1", 9999))

    assert learning_mode == [LearnSocketRule("connect_ex", Kind.TCP, "127.0.0.1", 9999, Direction.OUT, ())]


def test_sendto_records_a_learning_rule_instead_of_raising_when_refused(learning_mode: list[Any]) -> None:
    _arm("net=ALLOW|UDP|10.0.0.1|1|OUT")
    wrapped = patch_rules(learn=False)["socket.socket.sendto"](lambda *a, **k: len(a[1]))
    sock = _FakeSocket(SocketKind.SOCK_DGRAM)

    wrapped(sock, b"x", ("127.0.0.1", 9999))

    assert learning_mode == [LearnSocketRule("sendto", Kind.UDP, "127.0.0.1", 9999, Direction.OUT, ())]


def test_sendto_without_an_address_defers_to_the_builtin() -> None:
    """sendto(data) with no address at all is not this guard's problem: it must reach
    the real call so the builtin raises its own arity error, not a guard exception."""
    calls: list[tuple[Any, ...]] = []

    def _record(*args: Any, **_kwargs: Any) -> int:
        calls.append(args)
        return len(args[1])

    wrapped = patch_rules(learn=False)["socket.socket.sendto"](_record)
    sock = _FakeSocket(SocketKind.SOCK_DGRAM)

    result = wrapped(sock, b"x")

    assert result == 1
    assert calls == [(sock, b"x")]


# %% AF_UNIX and unsupported address-shape branches
#
# The pytest-only test scaffolding in guard_files (see its ``_deactivate_guard_files``)
# arms a wildcard expose-rw rule so that ordinary file tests are not forced to declare
# one: an AF_UNIX test must override ``guard_files._rules`` explicitly to see the real
# default-deny, or to prove a specific expose rule is what lets the access through.


def test_bind_allows_an_af_unix_path_covered_by_an_expose_rule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    errors: list[ErrorMsg] = []
    file_rules, _ = gf.parse_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 1)], errors)
    assert not errors
    monkeypatch.setattr(gf, "_rules", file_rules)
    socket_path = str(tmp_path / "allowed.sock")
    calls: list[tuple[Any, ...]] = []
    wrapped = patch_rules(learn=False)["socket.socket.bind"](lambda *a, **k: calls.append(a))
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    wrapped(sock, socket_path)

    assert calls == [(sock, socket_path)]


def test_bind_denies_an_af_unix_path_with_no_covering_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gf, "_rules", ())
    wrapped = _guarded("socket.socket.bind")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, "/tmp/does-not-matter.sock")


def test_bind_denies_an_address_shape_no_rule_can_evaluate() -> None:
    wrapped = _guarded("socket.socket.bind")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError, match="unsupported address"):
        wrapped(sock, 12345)  # neither a (host, port) tuple nor an AF_UNIX path


def test_connect_denies_an_af_unix_path_with_no_covering_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gf, "_rules", ())
    wrapped = _guarded("socket.socket.connect")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, "/tmp/does-not-matter.sock")


def test_connect_denies_an_address_shape_no_rule_can_evaluate() -> None:
    wrapped = _guarded("socket.socket.connect")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError, match="unsupported address"):
        wrapped(sock, 12345)


def test_connect_ex_denies_an_af_unix_path_with_no_covering_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gf, "_rules", ())
    wrapped = _guarded("socket.socket.connect_ex")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, "/tmp/does-not-matter.sock")


def test_connect_ex_denies_an_address_shape_no_rule_can_evaluate() -> None:
    wrapped = _guarded("socket.socket.connect_ex")
    sock = _FakeSocket(SocketKind.SOCK_STREAM)

    with pytest.raises(RuleSocketConnectionRefusedError, match="unsupported address"):
        wrapped(sock, 12345)


def test_sendto_denies_an_af_unix_path_with_no_covering_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gf, "_rules", ())
    wrapped = _guarded("socket.socket.sendto")
    sock = _FakeSocket(SocketKind.SOCK_DGRAM)

    with pytest.raises(RuleSocketConnectionRefusedError):
        wrapped(sock, b"x", "/tmp/does-not-matter.sock")


# %% Debug-logging branch of _check_address_with_rules


def test_check_address_with_rules_logs_debug_detail_for_hostname_and_direct_ip(
    mock_getaddrinfo: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """The refusal path is asserted through the exception type elsewhere in this
    suite; this test exercises the ALLOW debug-logging branch for a hostname address
    (quoted in the message) and then a direct-IP address (no quotes, no hostname),
    and checks the two distinct message shapes were both actually logged."""
    errors: list[ErrorMsg] = []
    rules, *_ = parse_rules([ConfigLine("net=ALLOW|any|0.0.0.0/0|*|OUT", Path(), 0)], errors)
    assert not errors
    mock_getaddrinfo.return_value = [(socket.AF_INET, Kind.TCP, 6, "", ("93.184.216.34", 80))]

    with caplog.at_level(logging.DEBUG, logger="Pysandboxes"):
        _check_address_with_rules(rules, Kind.TCP, ("example.com", 80), Direction.OUT)
        _check_address_with_rules(rules, Kind.TCP, ("93.184.216.34", 80), Direction.OUT)

    messages = [record.getMessage() for record in caplog.records]
    assert any("'example.com'" in message for message in messages)
    assert any("Connection to [93.184.216.34]:80 ALLOW" in message for message in messages)


# %% activate_guard re-activation


def test_activate_guard_refuses_a_second_activation() -> None:
    _arm("net=ALLOW|TCP|127.0.0.1|80|OUT")

    with pytest.raises(RuntimeError, match="already activated"):
        activate_guard(())


# %% _read_host_file platform branches
#
# These two simulate "win32" while actually running on whatever OS collected the
# test: the literal "System32\\drivers\\etc\\hosts" name is a single path component
# only where a backslash is an ordinary filename character, i.e. POSIX. On a real
# Windows collector the same component is a path separator, so both must be skipped.


@pytest.mark.skipif(sys.platform == "win32", reason="the simulated path needs a POSIX filesystem")
def test_read_host_file_reads_the_windows_hosts_file_when_systemroot_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    # A single path component: on POSIX, backslashes are ordinary filename characters.
    (tmp_path / "System32\\drivers\\etc\\hosts").write_text("198.51.100.43 win-only.example\n")

    dns, _inverse_dns = gs._read_host_file()

    assert "win-only.example" in dns


@pytest.mark.skipif(sys.platform == "win32", reason="the simulated path needs a POSIX filesystem")
def test_read_host_file_falls_back_to_the_default_windows_root_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.chdir(tmp_path)
    windows_root = tmp_path / "C:\\Windows"  # single literal component, same reason as above
    windows_root.mkdir()
    (windows_root / "System32\\drivers\\etc\\hosts").write_text("198.51.100.44 fallback-only.example\n")

    dns, _inverse_dns = gs._read_host_file()

    assert "fallback-only.example" in dns


def test_read_host_file_returns_empty_tables_on_an_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "aix")

    assert gs._read_host_file() == ({}, {})


# %% generate_rules: aliasing and duplicate-rule paths


def test_generate_rules_uses_a_hostname_already_known_and_aliases_it_via_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct access whose recorded address is already the *hostname* (not the
    resolved IP) must be recognised from ``dns`` directly, and the resulting
    destination must still go through the env-alias substitution."""
    monkeypatch.setattr(gs, "_read_host_file", lambda: ({}, {}))
    monkeypatch.setattr(gs.os, "environ", {"HOST_ALIAS": "pinned.example"})
    learned = {
        LearnSocketRule("getaddrinfo", Kind.UNKNOWN, "pinned.example", 0, Direction.OUT, (ip_address("198.51.100.7"),)),
        LearnSocketRule("connect", Kind.TCP, "pinned.example", 443, Direction.OUT, ()),
    }

    assert generate_rules(learned) == ["net=ALLOW|TCP|${HOST_ALIAS}|443|OUT"]


def test_generate_rules_masks_a_direct_ipv6_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gs, "_read_host_file", lambda: ({}, {}))
    monkeypatch.setattr(gs.os, "environ", {})
    learned = {LearnSocketRule("connect", Kind.TCP, "2001:db8::1", 443, Direction.OUT, ())}

    assert generate_rules(learned) == ["net=ALLOW|TCP|2001:db8::1/128|443|OUT"]


def test_generate_rules_aliases_a_known_port_and_ignores_a_non_numeric_port_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gs, "_read_host_file", lambda: ({}, {}))
    monkeypatch.setattr(gs.os, "environ", {"APP_PORT": "8443", "SOME_PORT_NAME": "not-a-number"})
    learned = {LearnSocketRule("connect", Kind.TCP, "203.0.113.10", 8443, Direction.OUT, ())}

    assert generate_rules(learned) == ["net=ALLOW|TCP|203.0.113.10/32|${APP_PORT}|OUT"]


def test_generate_rules_skips_an_in_rule_already_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the IN branch checks the currently-armed rules before adding a generated
    one. A positive control proves the same learned set does produce the rule when it
    is not already present, so the empty result below is the dedup, not a broken
    IN-rule generation."""
    monkeypatch.setattr(gs, "_read_host_file", lambda: ({}, {}))
    monkeypatch.setattr(gs.os, "environ", {})
    errors: list[ErrorMsg] = []
    existing_rule = "net=ALLOW|TCP|203.0.113.5/32|9999|IN"
    existing, _, _ = parse_rules([ConfigLine(existing_rule, Path(), 1)], errors)
    assert not errors
    learned = {LearnSocketRule("bind", Kind.TCP, "203.0.113.5", 9999, Direction.IN, ())}

    monkeypatch.setattr(gs, "_rules", ())
    assert generate_rules(learned) == [existing_rule]

    monkeypatch.setattr(gs, "_rules", existing)
    assert generate_rules(learned) == []
