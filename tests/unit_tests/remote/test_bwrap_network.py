# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression: without a socket rule, ``bwrap`` must not keep the host network."""

from pathlib import Path
from unittest.mock import patch

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_socket import parse_rules
from pysandboxes.immutable_dict import ImmutableDict
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
