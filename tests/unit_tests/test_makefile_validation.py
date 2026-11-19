# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2

"""Check the commands selected by the repository validation gates."""

import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _dry_run(target: str) -> str:
    return subprocess.run(
        ["make", "-n", "-o", "uv.lock", target], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def test_lint_covers_framework_cli_and_quick_demo() -> None:
    commands = _dry_run("lint")
    for path in ("pysandboxes/", "tests/", "python-sb/", "samples/quick-demo/app/"):
        assert path in commands


def test_validate_runs_each_sample_lint_from_its_locked_environment() -> None:
    commands = _dry_run("sample-lint")
    validate = _dry_run("validate")
    for sample in sorted((ROOT / "samples").glob("*-demo/uv.lock")):
        project = sample.parent.relative_to(ROOT).as_posix()
        assert f"--locked --project {project}" in commands
        assert f"--locked --project {project}" in validate


def test_release_build_and_audit_use_the_same_locked_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    release = set(project["dependency-groups"]["release"])
    assert {"hatchling", "hatch-vcs", "twine"} <= release
    audit = _dry_run("pip-audit-release")
    assert "--only-group release" in audit
    assert "pip-audit" in audit
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    build = workflow["jobs"]["build"]
    commands = "\n".join(step.get("run", "") for step in build["steps"])
    assert "--group release" in commands
    assert "--no-build-isolation" in commands
    assert "uvx twine" not in commands
