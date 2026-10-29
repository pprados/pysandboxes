# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Tests for macOS Seatbelt profile generation."""

import os
import stat
import threading
import time
from ipaddress import ip_network
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.remote.sandbox_exec_daemon import (
    _MAX_PROFILE_PORTS,
    SandboxExecSSEDaemon,
    _build_profile,
    _feed_profile,
    _ignore_paths,
    _network_ports,
    _network_rules,
    _symlink_directories,
)
from pysandboxes.sb_types import ConfigLine


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
        scratch_dir=tmp_path / "scratch",
        python_executable="/opt/python/bin/python",
        python_paths=("/opt/python/lib",),
        sse_port=45678,
    )


def test_profile_denies_by_default_and_quotes_read_write_paths(tmp_path: Path) -> None:
    exposed = tmp_path / 'read "this"-é'
    writable = tmp_path / "writable"
    runtime = (tmp_path / "runtime files-é").resolve()
    scratch = (tmp_path / "scratch").resolve()
    profile = _profile(
        tmp_path,
        files=(
            FSExposeRule(str(exposed), False, _line(f"expose-ro={exposed}")),
            FSExposeRule(str(writable), True, _line(f"expose-rw={writable}")),
        ),
    )

    assert "(deny default)" in profile
    assert f'(allow file-read* (subpath "{runtime}")' in profile
    assert f'(allow file-write* (subpath "{runtime}")' not in profile
    assert f'(allow file-read* (subpath "{scratch}")' in profile
    assert f'(allow file-write* (subpath "{scratch}")' in profile
    assert 'read \\"this\\"-é' in profile
    assert "(allow file-map-executable" in profile
    assert f'(allow file-map-executable (subpath "{exposed}")' not in profile


def test_the_dev_directory_is_not_granted_only_the_devices_named_by_a_rule(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path,
        files=(
            FSExposeRule("/dev/null", True, _line("<safe-devices>")),
            FSExposeRule("/dev/urandom", False, _line("<safe-devices>")),
        ),
    )

    assert '(subpath "/dev")' not in profile
    assert '(allow file-write* (subpath "/dev/null")' in profile
    assert '(allow file-read* (subpath "/dev/urandom")' in profile
    assert '(allow file-write* (subpath "/dev/urandom")' not in profile


def test_python_symlink_target_directories_are_available_to_seatbelt(tmp_path: Path) -> None:
    python_install = tmp_path / "python-install"
    python_bin = python_install / "bin"
    python_bin.mkdir(parents=True)
    python_executable = python_bin / "python3.13"
    python_executable.write_text("", encoding="utf-8")
    python_framework = python_install / "Python"
    python_framework.write_text("", encoding="utf-8")
    python_alias = tmp_path / "cpython-3.13-macos-x86_64-none"
    python_alias.symlink_to(python_install, target_is_directory=True)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.symlink_to(python_alias / "bin" / "python3.13")

    profile = _build_profile(
        EmptyRules,
        temp_dir=tmp_path / "runtime",
        scratch_dir=tmp_path / "scratch",
        python_executable=str(venv_python),
        python_paths=(),
        sse_port=45678,
    )

    assert f'(allow file-read* (subpath "{python_alias}")' in profile
    assert f'(allow file-map-executable (subpath "{python_alias}")' in profile
    assert f'(allow file-read* (subpath "{python_framework}")' in profile
    assert f'(allow file-map-executable (subpath "{python_framework}")' in profile
    assert f'(allow file-read-metadata (subpath "{venv_bin.parent}")' in profile
    assert f'(allow file-read* (subpath "{venv_bin.parent}")' not in profile


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


def _net(
    action: Action, kinds: tuple[Kind, ...], network: str, ports: tuple[int, ...] | range, direction: Direction
) -> SocketRule:
    return SocketRule(
        action,
        SocketMask(kinds, ip_network(network), ports),
        (direction,),
        _line(f"net={action.name}"),
    )


def _network(rules: tuple[SocketRule, ...], *, use_py_sandbox: bool = True) -> list[str]:
    return _network_rules(EmptyRules._replace(socket_rules=rules, use_py_sandbox=use_py_sandbox))


def test_a_deny_in_the_other_direction_does_not_remove_an_allow() -> None:
    allow = _net(Action.ALLOW, (Kind.TCP,), "0.0.0.0/0", (443,), Direction.OUT)
    deny = _net(Action.DENY, (Kind.TCP,), "0.0.0.0/0", (443,), Direction.IN)

    assert _network((allow, deny)) == ['(allow network-outbound (remote tcp "*:443"))']


def test_a_deny_too_wide_to_expand_removes_the_allows_it_may_cover() -> None:
    allow = _net(Action.ALLOW, (Kind.TCP,), "0.0.0.0/0", (443,), Direction.OUT)
    deny = _net(Action.DENY, (Kind.TCP,), "0.0.0.0/0", range(1, _MAX_PROFILE_PORTS + 2), Direction.OUT)

    assert _network((allow, deny)) == []


@pytest.mark.parametrize(
    ("allow_network", "deny_network"),
    [("0.0.0.0/0", "127.0.0.1/32"), ("127.0.0.1/32", "0.0.0.0/0"), ("127.0.0.1/32", "127.0.0.1/32")],
)
def test_a_deny_removes_an_allow_when_either_scope_is_any_host_or_both_match(
    allow_network: str, deny_network: str
) -> None:
    allow = _net(Action.ALLOW, (Kind.TCP,), allow_network, (443,), Direction.OUT)
    deny = _net(Action.DENY, (Kind.TCP,), deny_network, (443,), Direction.OUT)

    assert _network((allow, deny)) == []


def test_a_deny_of_one_kind_leaves_the_other_kinds_of_the_allow() -> None:
    allow = _net(Action.ALLOW, (Kind.TCP, Kind.UDP), "0.0.0.0/0", (443,), Direction.OUT)
    deny = _net(Action.DENY, (Kind.TCP,), "0.0.0.0/0", (443,), Direction.OUT)

    assert _network((allow, deny)) == ['(allow network-outbound (remote udp "*:443"))']


def test_a_rule_for_any_host_does_not_warn_about_widening(caplog: pytest.LogCaptureFixture) -> None:
    _network((_net(Action.ALLOW, (Kind.TCP,), "0.0.0.0/0", (443,), Direction.OUT),))

    assert not any("remote network hosts" in record.message for record in caplog.records)


def test_the_widening_warning_names_the_disabled_python_guard_only_when_it_is(caplog: pytest.LogCaptureFixture) -> None:
    host = (_net(Action.ALLOW, (Kind.TCP,), "203.0.113.7/32", (443,), Direction.OUT),)

    _network(host, use_py_sandbox=True)
    guarded = [r.message for r in caplog.records if "remote network hosts" in r.message]
    caplog.clear()
    _network(host, use_py_sandbox=False)
    unguarded = [r.message for r in caplog.records if "remote network hosts" in r.message]

    assert len(guarded) == 1 and "py-sandbox=false" not in guarded[0]
    assert len(unguarded) == 1 and "py-sandbox=false disables that guard" in unguarded[0]


def test_an_ignore_rule_is_absolute_or_relative_to_each_exposed_directory(tmp_path: Path) -> None:
    exposed = FSExposeRule(str(tmp_path), False, _line("expose-ro"))
    absolute = IgnoreRule("/a/../b", _line("ignore"))
    relative = IgnoreRule("x.txt", _line("ignore"))

    assert list(_ignore_paths(EmptyRules._replace(file_rules=(exposed, absolute)))) == ["/b"]
    assert list(_ignore_paths(EmptyRules._replace(file_rules=(relative,)))) == []
    assert list(_ignore_paths(EmptyRules._replace(file_rules=(exposed, relative)))) == [
        os.path.join(os.path.realpath(str(tmp_path)), "x.txt")
    ]


def test_a_chain_of_relative_directory_symlinks_is_followed_to_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "real" / "bin").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "real" / "bin")  # a link read as relative to the cwd would find nothing
    (tmp_path / "real" / "bin" / "python").write_text("", encoding="utf-8")
    os.symlink("real", tmp_path / "link2")
    os.symlink("link2", tmp_path / "link1")

    aliases = _symlink_directories(str(tmp_path / "link1" / "bin" / "python"))

    assert {str(tmp_path / "link1"), str(tmp_path / "link2")} <= aliases


def test_dns_permission_grants_the_system_resolver_socket_and_no_udp(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dns = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.UDP,), ip_network("0.0.0.0/0"), (53,)),
        (Direction.OUT,),
        _line("net=ALLOW|UDP|*|53|OUT"),
    )

    profile = _profile(tmp_path, sockets=(dns,), use_py_sandbox=False)

    assert '(allow network-outbound (literal "/private/var/run/mDNSResponder"))' in profile
    assert "remote udp" not in profile
    assert "network-inbound (local udp" not in profile
    assert any("resolver" in record.message for record in caplog.records)


def test_a_udp_rule_on_another_port_stays_a_port_rule(tmp_path: Path) -> None:
    ntp = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.UDP,), ip_network("0.0.0.0/0"), (123,)),
        (Direction.OUT,),
        _line("net=ALLOW|UDP|*|123|OUT"),
    )

    profile = _profile(tmp_path, sockets=(ntp,))

    assert '(allow network-outbound (remote udp "*:123"))' in profile
    assert "mDNSResponder" not in profile


def test_the_profile_reaches_sandbox_exec_through_a_pipe_read_once(tmp_path: Path) -> None:
    pipe = tmp_path / "seatbelt.sb"
    os.mkfifo(pipe, 0o600)
    profile = "(version 1)\n(deny default)\n" + '(allow file-read* (subpath "/usr"))\n' * 4000

    threading.Thread(target=_feed_profile, args=(pipe, profile), daemon=True).start()
    with open(pipe, encoding="utf-8") as reader:
        received = reader.read()

    assert received == profile
    deadline = time.monotonic() + 5
    while pipe.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not pipe.exists()


def test_a_pipe_nobody_opens_is_removed_after_the_timeout(tmp_path: Path) -> None:
    pipe = tmp_path / "seatbelt.sb"
    os.mkfifo(pipe, 0o600)

    _feed_profile(pipe, "(version 1)\n", timeout=0.2)

    assert not pipe.exists()


def test_the_daemon_creates_the_profile_pipe_private_to_its_user(tmp_path: Path) -> None:
    daemon = SandboxExecSSEDaemon("token")
    daemon.port = 45678
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    command, extra_envs = daemon.subprocess_cmd(EmptyRules, {}, run_dir / "pipe", run_dir)

    pipe = Path(command[command.index("-f") + 1])
    assert stat.S_ISFIFO(pipe.stat().st_mode)
    assert stat.S_IMODE(pipe.stat().st_mode) == 0o600
    assert extra_envs["TMPDIR"] == str(daemon.sandbox_temp())
    with open(pipe, encoding="utf-8") as reader:
        assert "(deny default)" in reader.read()
    daemon.release_sandbox_temp()


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


def _ports(ports: tuple[int, ...] | range, *, deny: bool = False) -> tuple[str, ...]:
    return _network_ports(
        _net(Action.DENY if deny else Action.ALLOW, (Kind.TCP,), "0.0.0.0/0", ports, Direction.OUT), deny=deny
    )


def test_the_whole_port_range_is_one_wildcard() -> None:
    assert _ports(range(0, 65536)) == ("*",)


def test_a_range_not_starting_at_zero_is_expanded_or_refused_not_wildcarded() -> None:
    assert _ports(range(1, 65536)) == ()
    assert _ports(range(0, 65535)) == ()


def test_a_port_list_exactly_at_the_limit_is_expanded() -> None:
    assert _ports(range(1, _MAX_PROFILE_PORTS + 1)) == tuple(str(port) for port in range(1, _MAX_PROFILE_PORTS + 1))


def test_the_parents_of_a_symlinked_python_directory_are_readable_as_metadata_only(tmp_path: Path) -> None:
    install = tmp_path / "install"
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "python3").write_text("", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "alias").symlink_to(install, target_is_directory=True)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(elsewhere / "alias" / "bin" / "python3")

    profile = _build_profile(
        EmptyRules,
        temp_dir=tmp_path / "runtime",
        scratch_dir=tmp_path / "scratch",
        python_executable=str(venv_bin / "python"),
        python_paths=(),
        sse_port=45678,
    )

    assert f'(allow file-read-metadata (subpath "{elsewhere}")' in profile
    assert f'(allow file-read* (subpath "{elsewhere}")' not in profile


def test_an_ignore_rule_does_not_stop_the_rules_that_follow_it(tmp_path: Path) -> None:
    exposed = tmp_path / "project"
    ignored = tmp_path / "secret.txt"
    profile = _profile(
        tmp_path,
        files=(
            IgnoreRule(str(ignored), _line(f"ignore={ignored}")),
            FSExposeRule(str(exposed), True, _line(f"expose-rw={exposed}")),
        ),
    )

    assert f'(allow file-write* (subpath "{exposed.resolve()}")' in profile


def test_the_profile_pipe_is_switched_to_blocking_writes(tmp_path: Path) -> None:
    pipe = tmp_path / "seatbelt.sb"
    os.mkfifo(pipe, 0o600)
    with patch("pysandboxes.remote.sandbox_exec_daemon.os.set_blocking", wraps=os.set_blocking) as set_blocking:
        threading.Thread(target=_feed_profile, args=(pipe, "(version 1)\n"), daemon=True).start()
        with open(pipe, encoding="utf-8") as reader:
            reader.read()
        deadline = time.monotonic() + 5
        while not set_blocking.called and time.monotonic() < deadline:
            time.sleep(0.01)

    assert set_blocking.call_args.args[1] is True


def test_feeding_a_pipe_that_is_already_gone_does_not_raise(tmp_path: Path) -> None:
    _feed_profile(tmp_path / "missing.sb", "(version 1)\n", timeout=0.1)


@pytest.mark.parametrize(
    ("is_file", "executable", "reason"),
    [
        (True, True, None),
        (True, False, "/usr/bin/sandbox-exec is missing or not executable"),
        (False, True, "/usr/bin/sandbox-exec is missing or not executable"),
    ],
)
def test_the_binary_must_be_a_file_and_executable(is_file: bool, executable: bool, reason: str | None) -> None:
    with (
        patch("pysandboxes.remote.sandbox_exec_daemon.sys.platform", "darwin"),
        patch("pysandboxes.remote.sandbox_exec_daemon.os.path.isfile", return_value=is_file),
        patch("pysandboxes.remote.sandbox_exec_daemon.os.access", return_value=executable),
    ):
        assert SandboxExecSSEDaemon.unavailable_reason() == reason


def test_the_profile_writer_thread_is_a_daemon_thread(tmp_path: Path) -> None:
    daemon = SandboxExecSSEDaemon("token")
    daemon.port = 45678
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with patch("pysandboxes.remote.sandbox_exec_daemon.threading.Thread") as thread:
        daemon.subprocess_cmd(EmptyRules, {}, run_dir / "pipe", run_dir)
    daemon.release_sandbox_temp()

    assert thread.call_args.kwargs["daemon"] is True
