# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression: without a socket rule, ``bwrap`` must not keep the host network."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_socket import parse_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import bwrap_sse_daemon as bwrap_mod
from pysandboxes.remote.bwrap_sse_daemon import BWrapSSEDaemon
from pysandboxes.sb_types import ConfigLine


def _bwrap_args(rules: AllRules, tmp_path: Path) -> list[str]:
    with patch("pysandboxes.remote.bwrap_sse_daemon.which_command", return_value="/usr/bin/bwrap"):
        return list(BWrapSSEDaemon("token")._bwrap_args(rules, {}, tmp_path / "pipe", tmp_path))


def _with_socket_rule() -> AllRules:
    socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
    return EmptyRules._replace(socket_rules=tuple(socket_rules))


def test_no_socket_rule_unshares_the_network(tmp_path: Path) -> None:
    """Default-deny: no ``net=`` rule means no network, not the host one."""
    args = _bwrap_args(EmptyRules, tmp_path)
    assert "--unshare-net" in args
    assert "--share-net" not in args


def test_no_socket_rule_needs_no_slirp(tmp_path: Path) -> None:
    """Nothing to filter: the child gets loopback only, no slirp4netns to start."""
    params = BWrapSSEDaemon("token").get_launch_params_for_python_sb(EmptyRules, 0, "t", "", tmp_path / "p", tmp_path)
    assert "on_launched" not in params
    assert not params["process_config"].wait_network


def test_socket_rule_unshares_the_network(tmp_path: Path) -> None:
    args = _bwrap_args(_with_socket_rule(), tmp_path)
    assert "--unshare-net" in args
    assert "--share-net" not in args


def test_share_net_keeps_the_host_network(tmp_path: Path) -> None:
    for params in ({"share-net": "yes"}, {"unshare-net": "no"}):
        for rules in (EmptyRules, _with_socket_rule()):
            args = _bwrap_args(rules._replace(os_sandbox_params=ImmutableDict(params)), tmp_path)
            assert "--share-net" in args
            assert "--unshare-net" not in args


def test_socket_rule_maps_the_caller_to_root_of_its_user_namespace(tmp_path: Path) -> None:
    """The host enters that namespace to load the filter: only a uid mapped to 0 keeps its capabilities there."""
    args = _bwrap_args(_with_socket_rule(), tmp_path)
    assert args[args.index("--unshare-user") :][:5] == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert "--cap-add" not in args


def test_no_socket_rule_keeps_the_caller_uid(tmp_path: Path) -> None:
    assert "--uid" not in _bwrap_args(EmptyRules, tmp_path)


def _filter_launch(tmp_path: Path) -> dict[str, Any]:
    with patch("pysandboxes.remote.bwrap_sse_daemon.which_command", return_value="/usr/bin/tool"):
        return BWrapSSEDaemon("token").get_launch_params_for_python_sb(
            _with_socket_rule(), 0, "t", "", tmp_path / "pipe", tmp_path
        )


def test_the_child_receives_nothing_to_apply_nor_to_wait_for(tmp_path: Path) -> None:
    """The sandboxed code holds no capability: the host loads the filter and waits for slirp4netns before it."""
    params = _filter_launch(tmp_path)
    config = params["process_config"]
    assert config.netfilter_rules == ()
    assert not config.wait_network
    assert config.slirp_ready_fd is None
    assert params["pass_fds"] == ()


def test_the_filter_is_loaded_before_slirp_and_from_the_sandbox_pid(tmp_path: Path) -> None:
    calls: list[str] = []

    def thread(**kw: Any) -> MagicMock:
        calls.append(kw["target"].__name__)
        return MagicMock()

    def ready(fd: int, timeout: float) -> bool:
        calls.append("ready")
        return True

    on_launched = _filter_launch(tmp_path)["on_launched"]
    with (
        patch.object(bwrap_mod, "_sandbox_pid", return_value=4242) as sandbox_pid,
        patch.object(bwrap_mod, "_apply_netfilter_from_host", side_effect=lambda pid, rules: calls.append(f"nf {pid}")),
        patch.object(bwrap_mod.threading, "Thread", side_effect=thread),
        patch.object(bwrap_mod, "_slirp_ready", side_effect=ready),
    ):
        on_launched(1000)
    sandbox_pid.assert_called_once_with(1000)
    assert calls[:3] == ["nf 4242", "run_slirp_watcher", "ready"]


def test_a_network_that_never_comes_up_kills_the_sandbox(tmp_path: Path) -> None:
    on_launched = _filter_launch(tmp_path)["on_launched"]
    with (
        patch.object(bwrap_mod, "_sandbox_pid", return_value=4242),
        patch.object(bwrap_mod, "_apply_netfilter_from_host"),
        patch.object(bwrap_mod.threading, "Thread"),
        patch.object(bwrap_mod, "_slirp_ready", return_value=False),
        patch.object(bwrap_mod.os, "kill") as kill,
        pytest.raises(SandBoxError, match="slirp4netns"),
    ):
        on_launched(1000)
    assert {c.args[0] for c in kill.call_args_list} == {1000, 4242}


def test_slirp_ready_reads_the_byte_and_sees_an_early_exit() -> None:
    r, w = os.pipe()
    os.write(w, b"1")
    assert bwrap_mod._slirp_ready(r, 1.0)
    os.close(w)
    assert not bwrap_mod._slirp_ready(r, 1.0)
    os.close(r)


def test_a_filter_that_cannot_be_loaded_kills_the_sandbox(tmp_path: Path) -> None:
    """Fail closed: the child stays blocked on its config pipe, so killing it means no code ever ran unfiltered."""
    (tmp_path / "pipe").write_text("")
    on_launched = _filter_launch(tmp_path)["on_launched"]
    with (
        patch.object(bwrap_mod, "_sandbox_pid", return_value=4242),
        patch.object(bwrap_mod, "_apply_netfilter_from_host", side_effect=SandBoxError("rejected")),
        patch.object(bwrap_mod.os, "kill") as kill,
        pytest.raises(SandBoxError, match="rejected"),
    ):
        on_launched(1000)
    killed = {c.args[0] for c in kill.call_args_list}
    assert killed == {1000, 4242}
    assert not (tmp_path / "pipe").exists()


def test_the_sandbox_pid_is_the_child_in_its_own_namespaces(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    for pid, net, uid_map in ((1000, "net:[1]", "0 1000 1"), (4242, "net:[2]", "0 1000 1")):
        (proc / str(pid) / "ns").mkdir(parents=True)
        (proc / str(pid) / "ns" / "net").symlink_to(net)
        (proc / str(pid) / "uid_map").write_text(uid_map)
    (proc / "1000" / "task" / "1000").mkdir(parents=True)
    (proc / "1000" / "task" / "1000" / "children").write_text("4242 ")
    (proc / "self").symlink_to(proc / "1000")
    with patch.object(bwrap_mod, "_PROC", proc):
        assert bwrap_mod._sandbox_pid(1000) == 4242


def test_a_sandbox_never_entering_its_namespaces_times_out(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    (proc / "1000" / "ns").mkdir(parents=True)
    (proc / "1000" / "ns" / "net").symlink_to("net:[1]")
    (proc / "self").symlink_to(proc / "1000")
    with patch.object(bwrap_mod, "_PROC", proc), pytest.raises(SandBoxError, match="namespace"):
        bwrap_mod._sandbox_pid(1000, timeout=0.05)
