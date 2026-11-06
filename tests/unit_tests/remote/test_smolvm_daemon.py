# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The host side of the smolvm provider: what it asks ``smolvm`` for, and what the guest is allowed to read."""

import sys
from pathlib import Path

import pytest

import pysandboxes
from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.smolvm_sse_daemon import SmolvmSSEDaemon
from pysandboxes.sb_types import ConfigLine, Envs


def _launch_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **params: str) -> str:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "smolvm").write_text("#!/bin/sh\n")
    (fake / "smolvm").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"image": "guest.tar", **params}))
    args, _ = SmolvmSSEDaemon("token").subprocess_cmd(rules, {}, tmp_path / "pipe", tmp_path)
    assert args[:2] == ["sh", "-c"]
    return args[2]


class TestLaunchCommand:
    def test_the_guest_is_unprivileged_unless_the_profile_says_otherwise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert " --unprivileged " in _launch_script(tmp_path, monkeypatch)
        assert "--unprivileged" not in _launch_script(tmp_path, monkeypatch, unprivileged="false")

    def test_the_guest_reads_its_config_from_the_mounted_file_and_runs_on_a_clean_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = _launch_script(tmp_path, monkeypatch)

        assert script.rstrip().endswith("--_named-pipe /pysb/config")
        assert "/usr/bin/env -i" in script
        assert "-v " + str(tmp_path / "smolvm-guest") + ":/pysb:ro" in script

    def test_a_key_smolvm_does_not_know_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SandBoxError, match="seccomp"):
            _launch_script(tmp_path, monkeypatch, seccomp="on")


class TestGuestRules:
    def test_the_guest_may_read_its_own_interpreter_and_the_package(self) -> None:
        user_rule = FSExposeRule("/data/", False, ConfigLine("expose-ro=/data", Path("profile"), 1))

        rules = SmolvmSSEDaemon("token").update_rules_and_activate(
            all_rules=EmptyRules._replace(file_rules=(user_rule,)), envs=Envs({})
        )

        readable = [r.path for r in rules.file_rules if isinstance(r, FSExposeRule) and not r.write]
        assert sys.base_prefix.rstrip("/") + "/lib/" in readable
        assert str(Path(pysandboxes.__file__).resolve().parent) + "/" in readable
        assert readable[-1] == "/data/", "the rules of the user come after, and are kept"

    def test_only_the_channel_socket_is_made_writable(self) -> None:
        rules = SmolvmSSEDaemon("token").update_rules_and_activate(all_rules=EmptyRules, envs=Envs({}))

        assert [r.path for r in rules.file_rules if isinstance(r, FSExposeRule) and r.write] == ["/tmp/pysb.sock"]
