# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Regression: bwrap must never bind the whole of ``/run``.

Binding ``/run`` outright exposed ``/run/docker.sock`` and every ``/run/user/<uid>``, including
another user's session D-Bus bus, which answers ``AUTH EXTERNAL OK`` from inside the sandbox --
a host escape. Only the real path ``/etc/resolv.conf`` resolves to, when it is a symlink into
``/run`` (as systemd-resolved publishes it), is needed and must be bound on its own.
"""

from pathlib import Path
from unittest.mock import patch

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote.bwrap_sse_daemon import BWrapSSEDaemon, _dns_run_paths


def _bwrap_args(tmp_path: Path) -> list[str]:
    with patch("pysandboxes.remote.bwrap_sse_daemon.which_command", return_value="/usr/bin/bwrap"):
        return list(BWrapSSEDaemon("token")._bwrap_args(EmptyRules, {}, tmp_path / "pipe", tmp_path))


def _binds(args: list[str]) -> list[tuple[str, str, str]]:
    """(flag, src, dest) for every *-bind* option in args."""
    binds = []
    i = 0
    while i < len(args):
        if args[i] in ("--ro-bind", "--bind", "--ro-bind-try", "--bind-try"):
            binds.append((args[i], args[i + 1], args[i + 2]))
            i += 3
        else:
            i += 1
    return binds


def test_run_itself_is_never_bound(tmp_path: Path) -> None:
    binds = _binds(_bwrap_args(tmp_path))
    assert not any(dest == "/run" for _, _, dest in binds)


def test_no_run_user_path_is_bound(tmp_path: Path) -> None:
    """/run/user/<uid> (sockets, session D-Bus bus) must stay unreachable."""
    binds = _binds(_bwrap_args(tmp_path))
    assert not any(dest.startswith("/run/user/") for _, _, dest in binds)


def test_resolv_conf_pointing_into_run_is_bound_on_its_own(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    target = run_root / "systemd" / "resolve" / "stub-resolv.conf"
    target.parent.mkdir(parents=True)
    target.write_text("nameserver 127.0.0.53\n")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.symlink_to(target)

    assert _dns_run_paths(resolv_conf, run_root) == [str(target)]


def test_plain_resolv_conf_needs_nothing_under_run(tmp_path: Path) -> None:
    """A static (non-symlink) resolv.conf is served by the whole-``/etc`` bind already."""
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text("nameserver 1.1.1.1\n")

    assert _dns_run_paths(resolv_conf, tmp_path / "run") == []


def test_resolv_conf_symlink_outside_run_root_is_ignored(tmp_path: Path) -> None:
    """Only the ``/run`` case needs special handling: ``/etc`` already covers any other target."""
    target = tmp_path / "elsewhere" / "resolv.conf"
    target.parent.mkdir()
    target.write_text("nameserver 1.1.1.1\n")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.symlink_to(target)

    assert _dns_run_paths(resolv_conf, tmp_path / "run") == []


def test_missing_resolv_conf_target_is_ignored(tmp_path: Path) -> None:
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.symlink_to(tmp_path / "run" / "does-not-exist")

    assert _dns_run_paths(resolv_conf, tmp_path / "run") == []
