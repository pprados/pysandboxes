# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The private temporary directory a daemon hands to its sandbox instead of the host's ``/tmp``."""

from pathlib import Path
from unittest.mock import MagicMock

from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon
from pysandboxes.remote.landlock_daemon import LandlockSSEDaemon


def test_the_directory_is_created_once_and_removed_on_release() -> None:
    daemon = SubProcessDaemon("token")

    first = daemon.sandbox_temp()

    assert first.is_dir()
    assert daemon.sandbox_temp() == first
    daemon.release_sandbox_temp()
    assert not first.exists()


def test_releasing_before_any_use_is_harmless_and_a_new_directory_follows() -> None:
    daemon = SubProcessDaemon("token")
    daemon.release_sandbox_temp()

    created = daemon.sandbox_temp()
    assert created.is_dir()
    daemon.release_sandbox_temp()


def test_landlock_points_tmpdir_at_the_daemons_directory_not_at_the_run_directory(tmp_path: Path) -> None:
    daemon = LandlockSSEDaemon("token")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _, extra_envs = daemon.subprocess_cmd(MagicMock(), {}, run_dir / "pipe", run_dir)

    assert extra_envs["TMPDIR"] == str(daemon.sandbox_temp())
    assert extra_envs["TMPDIR"] != str(run_dir)
    daemon.release_sandbox_temp()
