# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/find-nightly-gate.sh, the reuse-lookup job of release.yml."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "find-nightly-gate.sh"
SHA = "a" * 40

# Stands for gh: logs its arguments, answers `run list` from runs.json and `api .../runs/<id>/jobs` from jobs-<id>.json.
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DIR/calls"
case $1 in
  run) cat "$FAKE_DIR/runs.json" ;;
  api) id=${!#}; id=${id#*/runs/}; cat "$FAKE_DIR/jobs-${id%%/*}.json" ;;
esac
"""


def _run(id_: int, sha: str = SHA, event: str = "schedule") -> dict[str, object]:
    return {
        "databaseId": id_,
        "url": f"https://example/runs/{id_}",
        "headSha": sha,
        "event": event,
        "status": "completed",
    }


def _jobs(conclusion: str = "success", **overrides: str) -> list[dict[str, str]]:
    names = [
        "integration / integration (3.11)",
        "integration / integration (3.14)",
        "samples / samples (3.11)",
        "containers / containers (docker)",
    ]
    return [{"name": "changes", "conclusion": "success"}] + [
        {"name": n, "conclusion": overrides.get(n, conclusion)} for n in names
    ]


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (tmp_path / "runs.json").write_text("[]")
    return tmp_path


def _pages(fake: Path, id_: int, *pages: list[dict[str, str]]) -> None:
    # gh api --paginate prints one JSON object per page, back to back.
    (fake / f"jobs-{id_}.json").write_text("".join(json.dumps({"jobs": p}) for p in pages))


def _lookup(fake: Path, runs: list[dict[str, object]]) -> dict[str, str]:
    (fake / "runs.json").write_text(json.dumps(runs))
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "GH_REPO": "o/r",
    }
    result = subprocess.run(["bash", str(SCRIPT), SHA], env=env, capture_output=True, text=True, check=True)
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_a_nightly_whose_suites_all_passed_is_reused(fake: Path) -> None:
    _pages(fake, 7, _jobs())
    assert _lookup(fake, [_run(7)]) == {
        "reuse": "true",
        "run": "https://example/runs/7",
    }


def test_only_completed_nightly_runs_of_full_gate_on_develop_at_the_commit_are_asked_for(
    fake: Path,
) -> None:
    _lookup(fake, [])
    call = (fake / "calls").read_text().split()
    assert call[:2] == ["run", "list"]
    options = dict(zip(call[2::2], call[3::2], strict=True))
    assert options["--workflow"] == "full-gate.yml"
    assert options["--event"] == "schedule"
    assert options["--branch"] == "develop"
    assert options["--commit"] == SHA
    assert options["--status"] == "completed"
    assert options["--limit"] == "100"


def test_no_nightly_on_the_commit_means_no_reuse(fake: Path) -> None:
    assert _lookup(fake, []) == {"reuse": "false"}


def test_a_nightly_whose_guard_skipped_the_suites_is_not_reused(fake: Path) -> None:
    _pages(fake, 7, _jobs("skipped"))
    assert _lookup(fake, [_run(7)]) == {"reuse": "false"}


def test_one_failed_suite_job_prevents_reuse(fake: Path) -> None:
    _pages(fake, 7, _jobs(**{"samples / samples (3.11)": "failure"}))
    assert _lookup(fake, [_run(7)]) == {"reuse": "false"}


def test_a_nightly_missing_a_whole_suite_is_not_reused(fake: Path) -> None:
    _pages(fake, 7, [j for j in _jobs() if not j["name"].startswith("containers")])
    assert _lookup(fake, [_run(7)]) == {"reuse": "false"}


@pytest.mark.parametrize("run", [_run(7, sha="b" * 40), _run(7, event="workflow_dispatch")])
def test_a_run_of_another_commit_or_event_is_not_reused_even_if_listed(fake: Path, run: dict[str, object]) -> None:
    _pages(fake, 7, _jobs())
    assert _lookup(fake, [run]) == {"reuse": "false"}


def test_a_later_green_nightly_is_reused_after_a_red_one(fake: Path) -> None:
    _pages(fake, 7, _jobs("failure"))
    _pages(fake, 8, _jobs())
    assert _lookup(fake, [_run(7), _run(8)]) == {
        "reuse": "true",
        "run": "https://example/runs/8",
    }


def test_jobs_spread_over_several_pages_are_read_together(fake: Path) -> None:
    jobs = _jobs()
    _pages(fake, 7, jobs[:3], jobs[3:])
    assert _lookup(fake, [_run(7)]) == {
        "reuse": "true",
        "run": "https://example/runs/7",
    }
