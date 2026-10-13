# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Tests for macOS Seatbelt profile generation."""

from ipaddress import ip_network
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.sb_types import ConfigLine
from pysandboxes.remote.sandbox_exec_daemon import SandboxExecSSEDaemon, _build_profile


def _line(rule: str) -> ConfigLine:
    return ConfigLine(rule, Path("profile"), 1)


def _profile(
    tmp_path: Path,
    *,
    files: tuple[FSExposeRule | IgnoreRule, ...] = (),
    sockets: tuple[SocketRule, ...] = (),
    use_py_sandbox: bool = True,
) -> str:
    rules = EmptyRules._replace(
        file_rules=files,
        socket_rules=sockets,
        use_py_sandbox=use_py_sandbox,
    )
    return _build_profile(
        rules,
        temp_dir=tmp_path / "runtime files-é",
        python_executable="/opt/python/bin/python",
        python_paths=("/opt/python/lib",),
        sse_port=45678,
    )


def test_profile_denies_by_default_and_quotes_read_write_paths(tmp_path: Path) -> None:
    exposed = tmp_path / 'read "this"-é'
    writable = tmp_path / "writable"
    runtime = (tmp_path / "runtime files-é").resolve()
    profile = _profile(
        tmp_path,
        files=(
            FSExposeRule(str(exposed), False, _line(f"expose-ro={exposed}")),
            FSExposeRule(str(writable), True, _line(f"expose-rw={writable}")),
        ),
    )

    assert "(deny default)" in profile
    assert f'(allow file-read* (subpath "{runtime}")' in profile
    assert f'(allow file-write* (subpath "{runtime}")' in profile
    assert 'read \\"this\\"-é' in profile
    assert "(allow file-map-executable" in profile
    assert f'(allow file-map-executable (subpath "{exposed}")' not in profile


def test_ignore_rule_is_a_deny_after_exposed_ancestor(tmp_path: Path) -> None:
    exposed = tmp_path / "project"
    ignored = exposed / "secret*.txt"
    profile = _profile(
        tmp_path,
        files=(
            FSExposeRule(str(exposed), False, _line(f"expose-ro={exposed}")),
            IgnoreRule(str(ignored), _line(f"ignore={ignored}")),
        ),
    )

    assert profile.index("(allow file-read* (subpath") < profile.index("(deny file-read* file-write*")
    assert "secret.*\\.txt" in profile


def test_network_rules_allow_protocol_and_port_and_default_deny(tmp_path: Path) -> None:
    tcp = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("0.0.0.0/0"), (443,)),
        (Direction.OUT,),
        _line("net=ALLOW|TCP|*|443|OUT"),
    )
    loopback = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("127.0.0.1/32"), (45678,)),
        (Direction.IN,),
        _line("net=ALLOW|TCP|localhost|45678|IN"),
    )
    profile = _profile(tmp_path, sockets=(tcp, loopback))

    assert "(deny network*)" in profile
    assert '(allow network-outbound (remote tcp "*:443"))' in profile
    assert '(allow network-bind (local tcp "localhost:45678"))' in profile
    assert '(allow network-inbound (local tcp "localhost:45678"))' in profile


def test_remote_host_loss_warns_when_python_guards_are_disabled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    remote = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("203.0.113.7/32"), (443,)),
        (Direction.OUT,),
        _line("net=ALLOW|TCP|203.0.113.7|443|OUT"),
    )
    profile = _profile(tmp_path, sockets=(remote,), use_py_sandbox=False)

    assert '(allow network-outbound (remote tcp "*:443"))' in profile
    assert any("remote network hosts" in record.message.lower() for record in caplog.records)


def test_dns_permission_warns_about_unrestricted_udp_replies(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    dns = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.UDP,), ip_network("0.0.0.0/0"), (53,)),
        (Direction.OUT,),
        _line("net=ALLOW|UDP|*|53|OUT"),
    )

    profile = _profile(tmp_path, sockets=(dns,), use_py_sandbox=False)

    assert '(allow network-outbound (remote udp "*:53"))' in profile
    assert "(allow network-inbound (local udp))" in profile
    assert any("DNS" in record.message for record in caplog.records)


def test_deny_socket_rule_is_not_widened_to_an_allow(tmp_path: Path) -> None:
    denied = SocketRule(
        Action.DENY,
        SocketMask((Kind.TCP,), ip_network("0.0.0.0/0"), (443,)),
        (Direction.OUT,),
        _line("net=DENY|TCP|*|443|OUT"),
    )

    profile = _profile(tmp_path, sockets=(denied,))

    assert '(allow network-outbound (remote tcp "*:443"))' not in profile


def test_ephemeral_port_zero_is_not_emitted_as_invalid_sbpl(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    rule = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("127.0.0.1/32"), (0, 443)),
        (Direction.OUT,),
        _line("net=ALLOW|TCP|127.0.0.1|0,443|OUT"),
    )
    profile = _profile(tmp_path, sockets=(rule,))

    assert '(allow network-outbound (remote tcp "localhost:443"))' in profile
    assert "localhost:0" not in profile
    assert "port 0 or an ephemeral port" in caplog.text


def test_provider_availability_checks_platform_and_binary() -> None:
    with patch("pysandboxes.remote.sandbox_exec_daemon.sys.platform", "linux"):
        assert SandboxExecSSEDaemon.unavailable_reason() == "sandbox-exec is only available on macOS"

    with (
        patch("pysandboxes.remote.sandbox_exec_daemon.sys.platform", "darwin"),
        patch("pysandboxes.remote.sandbox_exec_daemon.os.path.isfile", return_value=False),
    ):
        assert SandboxExecSSEDaemon.unavailable_reason() == "/usr/bin/sandbox-exec is missing or not executable"


def test_specific_deny_suppresses_a_wider_allow_for_the_same_port(tmp_path: Path) -> None:
    allowed = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("0.0.0.0/0"), range(65536)),
        (Direction.OUT,),
        _line("net=ALLOW|TCP|*|*|OUT"),
    )
    denied = SocketRule(
        Action.DENY,
        SocketMask((Kind.TCP,), ip_network("203.0.113.7/32"), (443,)),
        (Direction.OUT,),
        _line("net=DENY|TCP|203.0.113.7|443|OUT"),
    )

    profile = _profile(tmp_path, sockets=(allowed, denied))

    assert '(allow network-outbound (remote tcp "*:*"))' not in profile
