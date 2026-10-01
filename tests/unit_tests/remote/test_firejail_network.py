# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression: firejail must never run a jail on the host network with only the Python layer denying."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_socket import parse_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote.firejail_sse_daemon import FireJailSSEDaemon
from pysandboxes.sb_types import ConfigLine, Envs


def _firejail_args(rules: AllRules, tmp_path: Path, config: str | None) -> list[str]:
    config_path = tmp_path / "firejail.config"
    if config is not None:
        config_path.write_text(config, encoding="utf-8")
    with (
        patch.object(firejail_sse_daemon, "FIREJAIL_CONFIG", config_path),
        patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"),
        patch.object(firejail_sse_daemon, "get_upstream_dns", return_value=[]),
        patch.object(firejail_sse_daemon, "get_default_interface", return_value="eth0"),
        patch.object(firejail_sse_daemon, "get_bridge_interfaces", return_value=[]),
    ):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    return list(args)


def _with_socket_rule() -> AllRules:
    socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
    return EmptyRules._replace(socket_rules=tuple(socket_rules))


@pytest.mark.parametrize("config", ["restricted-network yes\n", "restricted-network no\n", None])
def test_no_socket_rule_denies_the_network(tmp_path: Path, config: str | None) -> None:
    """Default-deny: no ``net=`` rule means loopback only, allowed to regular users even when restricted."""
    args = _firejail_args(EmptyRules, tmp_path, config)
    assert "--net=none" in args
    assert "--x11=none" in args


def test_explicit_net_param_is_kept(tmp_path: Path) -> None:
    """``firejail.net=`` is the author's choice: no ``--net=none`` on top of it."""
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"net": "docker0"}))
    args = _firejail_args(rules, tmp_path, "restricted-network no\n")
    assert "--net=docker0" in args
    assert "--net=none" not in args


@pytest.mark.parametrize("config", ["restricted-network yes\n", None])
def test_socket_rule_with_restricted_network_refuses_to_start(tmp_path: Path, config: str | None) -> None:
    """Socket rules cannot be enforced by the kernel there: refuse instead of keeping the host network."""
    with pytest.raises(SystemExit):
        _firejail_args(_with_socket_rule(), tmp_path, config)


def test_socket_rule_without_restriction_gets_its_own_network(tmp_path: Path) -> None:
    args = _firejail_args(_with_socket_rule(), tmp_path, "restricted-network no\n")
    assert "--net=eth0" in args
    assert "--net=none" not in args


@pytest.mark.parametrize("with_socket_rule", [False, True])
def test_environment_is_always_cleared_last(tmp_path: Path, with_socket_rule: bool) -> None:
    """``env -i`` takes everything after it as its own argv, so it must close the firejail options."""
    rules = _with_socket_rule() if with_socket_rule else EmptyRules
    rules = rules._replace(envs=Envs({"TERM": "xterm"}))
    args = _firejail_args(rules, tmp_path, "restricted-network no\n")
    env_at = args.index("/usr/bin/env")
    assert args[env_at:] == ["/usr/bin/env", "-i", "TERM=xterm"]
    assert all(not a.startswith("--") for a in args[env_at:])
