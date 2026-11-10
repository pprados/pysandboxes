# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The host side of the smolvm provider: what it asks ``smolvm`` for, and what the guest is allowed to read."""

import subprocess
from pathlib import Path

import pytest

import pysandboxes
from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import smolvm_sse_daemon
from pysandboxes.remote.smolvm_sse_daemon import SmolvmSSEDaemon
from pysandboxes.sb_types import ConfigLine, Envs


def _launch_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_rules: tuple[FSExposeRule, ...] = (), **params: str
) -> str:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "smolvm").write_text("#!/bin/sh\n")
    (fake / "smolvm").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    rules = EmptyRules._replace(
        os_sandbox_params=ImmutableDict({"image": "guest.tar", **params}), file_rules=file_rules
    )
    args, _ = SmolvmSSEDaemon("token").subprocess_cmd(rules, {}, tmp_path / "pipe", tmp_path)
    assert args[:2] == ["sh", "-c"]
    return args[2]


class TestLaunchCommand:
    def test_the_config_reaches_the_guest_through_its_standard_input_and_never_the_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = _launch_script(tmp_path, monkeypatch)

        assert script.rstrip().endswith('"$@" --_config-on-stdin')
        assert 'exec 0< "$fifo"' in script
        assert " -i " in script
        assert "cat " not in script, "the FIFO is not copied to a file"

    def test_the_standard_input_of_python_sb_follows_the_config_and_a_daemon_keeps_its_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = _launch_script(tmp_path, monkeypatch)
        (tmp_path / "pipe").write_bytes(b"CONFIG")
        record = tmp_path / "stdin-of-the-guest"
        (tmp_path / "bin" / "smolvm").write_text(f"#!/bin/sh\ncat > {record}\n")

        def run(*user_args: str, stdin: bytes) -> bytes:
            done = subprocess.run(
                ["sh", "-c", script, "smolvm-launcher", *user_args, "--_named-pipe", str(tmp_path / "pipe")],
                input=stdin,
                capture_output=True,
                env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"},
                timeout=30,
            )
            assert done.returncode == 0, done.stderr
            return record.read_bytes()

        assert run("script.py", "--_python-sb", stdin=b"SCRIPT") == b"CONFIGSCRIPT"
        assert run("script.py", stdin=b"SCRIPT") == b"CONFIG", "a daemon never takes the stdin of its application"

    def test_the_guest_runs_a_script_that_drops_its_capabilities_and_clears_its_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = _launch_script(tmp_path, monkeypatch)

        assert "--bounding-set=-all" in script and "--no-new-privs" in script
        assert "env -i" in script
        assert "--unprivileged" not in script, "the init script needs the capability to mount"

    def test_the_package_is_shared_read_only_and_nothing_else_of_the_host_is_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = _launch_script(tmp_path, monkeypatch)

        assert script.count(" -v ") == 1
        assert ":ro" in script

    def test_a_package_smolvm_cannot_share_is_taken_from_the_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(smolvm_sse_daemon, "_PACKAGE_DIR", Path("/usr/lib/python3/dist-packages/pysandboxes"))

        script = _launch_script(tmp_path, monkeypatch)

        assert "PYTHONPATH" not in script
        assert script.count(" -v ") == 0

    def test_a_package_smolvm_can_share_is_shared_and_wins_over_the_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = tmp_path / "src" / "pysandboxes"
        package.mkdir(parents=True)
        monkeypatch.setattr(smolvm_sse_daemon, "_PACKAGE_DIR", package)

        script = _launch_script(tmp_path, monkeypatch)

        assert f"PYTHONPATH={package.parent}" in script
        assert f"{package}:" in script

    def test_a_profile_that_needs_more_shares_than_a_guest_takes_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directories = [tmp_path / f"w{i}" for i in range(8)]
        for directory in directories:
            directory.mkdir()
        file_rules = tuple(
            FSExposeRule(f"{directory}/", True, ConfigLine("", Path("p"), 1)) for directory in directories
        )

        with pytest.raises(SandBoxError, match="shares of the host"):
            _launch_script(tmp_path, monkeypatch, file_rules=file_rules)

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
        assert "/usr/local/lib/" in readable, "the interpreter of the image, not the host's"
        assert str(Path(pysandboxes.__file__).resolve().parent) + "/" in readable
        assert readable[-1] == "/data/", "the rules of the user come after, and are kept"

    def test_only_the_channel_socket_is_made_writable(self) -> None:
        rules = SmolvmSSEDaemon("token").update_rules_and_activate(all_rules=EmptyRules, envs=Envs({}))

        assert [r.path for r in rules.file_rules if isinstance(r, FSExposeRule) and r.write] == ["/tmp/pysb.sock"]
