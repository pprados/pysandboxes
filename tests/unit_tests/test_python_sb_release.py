# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/python-sb-changes.sh: release.yml publishes python-sb only when python-sb/ changed."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "python-sb-changes.sh"
_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=_ENV, check=True, capture_output=True)


def _pyproject(repo: Path, version: str, extra: str = "") -> None:
    (repo / "python-sb" / "pyproject.toml").write_text(f'[project]\nname = "python-sb"\nversion = "{version}"\n{extra}')


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "develop")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "user.email", "t@example.com")
    (tmp_path / "python-sb").mkdir()
    _pyproject(tmp_path, "0.0.1")
    (tmp_path / "core.py").write_text("v1\n")
    _commit(tmp_path, "init")
    _git(tmp_path, "tag", "v0.1.0b1")
    return tmp_path


def _changes(repo: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), tag], cwd=repo, env=_ENV, capture_output=True, text=True, check=False)


def test_a_release_that_leaves_python_sb_alone_does_not_publish_it(repo: Path) -> None:
    (repo / "core.py").write_text("v2\n")
    _commit(repo, "core")
    _git(repo, "tag", "v0.1.0b2")
    result = _changes(repo, "v0.1.0b2")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["publish=false", "version=0.0.1"]


def test_a_change_with_a_bumped_version_publishes_python_sb(repo: Path) -> None:
    _pyproject(repo, "0.0.2", 'dependencies = ["pysandboxes>=0.1.0b1"]\n')
    _commit(repo, "python-sb")
    _git(repo, "tag", "v0.1.0b2")
    result = _changes(repo, "v0.1.0b2")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["publish=true", "version=0.0.2"]


@pytest.mark.parametrize("version", ["0.0.1", "0.0.0"])
def test_a_change_without_a_higher_version_fails_the_release(repo: Path, version: str) -> None:
    (repo / "python-sb" / "README.md").write_text("new\n")
    _pyproject(repo, version)
    _commit(repo, "python-sb")
    _git(repo, "tag", "v0.1.0b2")
    result = _changes(repo, "v0.1.0b2")
    assert result.returncode != 0
    assert "bump" in result.stderr
    assert "v0.1.0b1" in result.stderr


def test_versions_compare_by_number_not_by_text(repo: Path) -> None:
    _pyproject(repo, "0.0.9")
    _commit(repo, "python-sb 0.0.9")
    _git(repo, "tag", "v0.1.0b2")
    _pyproject(repo, "0.0.10")
    _commit(repo, "python-sb 0.0.10")
    _git(repo, "tag", "v0.1.0b3")
    assert _changes(repo, "v0.1.0b3").stdout.split() == ["publish=true", "version=0.0.10"]


def test_the_previous_tag_is_the_nearest_release_before_this_one(repo: Path) -> None:
    _pyproject(repo, "0.0.2")
    _commit(repo, "python-sb")
    _git(repo, "tag", "v0.1.0b2")
    (repo / "core.py").write_text("v3\n")
    _commit(repo, "core")
    _git(repo, "tag", "v0.1.0b3")
    assert _changes(repo, "v0.1.0b3").stdout.split() == ["publish=false", "version=0.0.2"]


def test_the_first_release_publishes_python_sb(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "develop")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "user.email", "t@example.com")
    (tmp_path / "python-sb").mkdir()
    _pyproject(tmp_path, "0.0.1")
    _commit(tmp_path, "init")
    _git(tmp_path, "tag", "v0.1.0b1")
    assert _changes(tmp_path, "v0.1.0b1").stdout.split() == ["publish=true", "version=0.0.1"]
