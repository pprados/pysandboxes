# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Regression: firejail aborts on ``--whitelist=/proc``, a path learning mode writes."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import parse_rules
from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote.firejail_sse_daemon import FireJailSSEDaemon
from pysandboxes.sb_types import ConfigLine


def _firejail_args(rule: str, tmp_path: Path) -> list[str]:
    file_rules, _ = parse_rules([ConfigLine(rule, Path(), 0)], [])
    rules = EmptyRules._replace(file_rules=tuple(file_rules))
    with patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    return list(args)


@pytest.mark.parametrize("path", ["/proc", "/proc/sys/kernel/random"])
def test_a_proc_path_is_not_whitelisted(tmp_path: Path, path: str) -> None:
    """firejail mounts its own /proc and refuses it as a whitelist: "invalid whitelist path /proc"."""
    args = _firejail_args(f"expose-ro={path}", tmp_path)
    assert not [arg for arg in args if arg.startswith("--whitelist=/proc")]
    assert f"--read-only={path}/" in args


def test_a_profile_rlimit_replaces_the_template_one(tmp_path: Path) -> None:
    """A library that maps more than 300 MB at import needs a larger --rlimit-as for its profile alone."""
    params, unparsed = FireJailSSEDaemon("token").parse_rules([ConfigLine("firejail.rlimit-as=600m", Path(), 0)], [])
    assert unparsed == []
    rules = EmptyRules._replace(os_sandbox_params=params)
    with patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    assert [arg for arg in args if arg.startswith("--rlimit-as=")] == ["--rlimit-as=600m"]
