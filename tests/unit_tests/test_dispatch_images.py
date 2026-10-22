# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/dispatch-images.sh, the images job of release.yml."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "dispatch-images.sh"

# Stands for gh: logs its arguments, answers `run list` with the --jq program applied to RUNS (a JSON array), and
# `run watch` with the exit code of WATCH_EXIT. `sleep` is shadowed below, so the polling loop costs nothing.
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DIR/calls"
case "$1 $2" in
  "run list") jq -r "${@: -1}" <<<"$RUNS" ;;
  "run watch") exit "${WATCH_EXIT:-0}" ;;
esac
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "sleep").write_text("#!/usr/bin/env bash\n")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return tmp_path


def _dispatch(fake: Path, runs: str, watch_exit: int = 0) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "GITHUB_REPOSITORY": "o/r",
        "RUNS": runs,
        "WATCH_EXIT": str(watch_exit),
    }
    return subprocess.run(["bash", str(SCRIPT), "v1.2.3"], env=env, capture_output=True, text=True)


def _calls(fake: Path) -> list[str]:
    return (fake / "calls").read_text().splitlines()


def test_it_dispatches_images_on_the_tag_and_waits_for_the_run_it_started(fake: Path) -> None:
    runs = (
        '[{"databaseId": 7, "createdAt": "2999-01-01T00:00:00Z"},'
        ' {"databaseId": 3, "createdAt": "2000-01-01T00:00:00Z"}]'
    )
    result = _dispatch(fake, runs)
    assert result.returncode == 0, result.stderr
    calls = _calls(fake)
    assert calls[0] == "workflow run images.yml --ref v1.2.3"
    assert "--workflow images.yml --event workflow_dispatch --branch v1.2.3" in calls[1]
    assert calls[-1] == "run watch 7 --interval 30 --exit-status"
    assert "actions/runs/7" in result.stdout


def test_it_ignores_a_run_that_began_before_the_dispatch(fake: Path) -> None:
    result = _dispatch(fake, '[{"databaseId": 3, "createdAt": "2000-01-01T00:00:00Z"}]')
    assert result.returncode == 1
    assert "did not appear" in result.stderr
    assert not any(call.startswith("run watch") for call in _calls(fake))


def test_it_fails_when_the_dispatched_run_fails(fake: Path) -> None:
    result = _dispatch(fake, '[{"databaseId": 7, "createdAt": "2999-01-01T00:00:00Z"}]', watch_exit=1)
    assert result.returncode == 1
