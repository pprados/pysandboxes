# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Regression: firejail aborts on ``--whitelist=/proc``, a path learning mode writes."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule, parse_rules
from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote.firejail_sse_daemon import FireJailSSEDaemon
from pysandboxes.sb_types import ConfigLine

_CONFIG = ConfigLine("x", Path(), 1)


def _firejail_args(rule: str, tmp_path: Path) -> list[str]:
    file_rules, _ = parse_rules([ConfigLine(rule, Path(), 0)], [])
    rules = EmptyRules._replace(file_rules=tuple(file_rules))
    with patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    return list(args)


def _firejail_args_for_rules(rules: EmptyRules, tmp_path: Path) -> list[str]:
    with patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    return list(args)


@pytest.mark.parametrize("path", ["/proc", "/proc/sys/kernel/random"])
@pytest.mark.skipif(sys.platform != "linux", reason="Firejail's /proc mount behavior is Linux-specific")
def test_a_proc_path_is_not_whitelisted(tmp_path: Path, path: str) -> None:
    """firejail mounts its own /proc and refuses it as a whitelist: "invalid whitelist path /proc"."""
    args = _firejail_args(f"expose-ro={path}", tmp_path)
    assert not [arg for arg in args if arg.startswith("--whitelist=/proc")]
    assert f"--read-only={path}/" in args


@pytest.mark.skipif(sys.platform != "linux", reason="Firejail's /etc handling is Linux-specific")
def test_etc_is_not_whitelisted(tmp_path: Path) -> None:
    """--private-etc provides /etc: a whitelist there puts a tmpfs over it and --dns fails."""
    args = _firejail_args("expose-ro=/etc", tmp_path)
    assert not [arg for arg in args if arg.startswith("--whitelist=/etc")]


def test_an_ignore_rule_hides_matching_files_in_subdirectories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--blacklist`` does not descend into subdirectories: the pattern must resolve to real paths first."""
    (tmp_path / "sub").mkdir()
    (tmp_path / ".env").write_text("TOP=1", encoding="utf-8")
    (tmp_path / "sub" / ".env").write_text("NESTED=1", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    args = _firejail_args("ignore=.env", tmp_path)

    assert f"--blacklist={tmp_path / '.env'}" in args
    assert f"--blacklist={tmp_path / 'sub' / '.env'}" in args


def test_an_ignored_file_under_an_exposed_path_outside_cwd_is_blacklisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ignore=`` must mask a match anywhere the sandbox can reach, not only under cwd."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("SECRET=1", encoding="utf-8")
    monkeypatch.chdir(cwd)
    rules = EmptyRules._replace(file_rules=(FSExposeRule(str(data) + "/", False, _CONFIG), IgnoreRule(".env", _CONFIG)))

    args = _firejail_args_for_rules(rules, tmp_path)

    assert f"--blacklist={data / '.env'}" in args


def test_without_the_ignore_rule_the_exposed_file_is_not_blacklisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control for the test above: the rule, not the exposure, causes the blacklist."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("SECRET=1", encoding="utf-8")
    monkeypatch.chdir(cwd)
    rules = EmptyRules._replace(file_rules=(FSExposeRule(str(data) + "/", False, _CONFIG),))

    args = _firejail_args_for_rules(rules, tmp_path)

    assert f"--blacklist={data / '.env'}" not in args


def test_a_profile_rlimit_replaces_the_template_one(tmp_path: Path) -> None:
    """A library that maps more than 300 MB at import needs a larger --rlimit-as for its profile alone."""
    params, unparsed = FireJailSSEDaemon("token").parse_rules([ConfigLine("firejail.rlimit-as=600m", Path(), 0)], [])
    assert unparsed == []
    rules = EmptyRules._replace(os_sandbox_params=params)
    with patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, None, tmp_path)
    assert [arg for arg in args if arg.startswith("--rlimit-as=")] == ["--rlimit-as=600m"]
