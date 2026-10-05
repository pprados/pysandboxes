# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/checked-commits.sh: the commits whose push runs vouch for a tagged commit."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "checked-commits.sh"
_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, env=_ENV, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, *files: str) -> str:
    for name in files:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((path.read_text() if path.exists() else "") + "x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "develop")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "user.email", "t@example.com")
    return tmp_path


def _checked(repo: Path, sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), sha], cwd=repo, env=_ENV, capture_output=True, text=True, check=False)


def test_a_code_commit_vouches_for_itself_only(repo: Path) -> None:
    _commit(repo, "pysandboxes/x.py")
    code = _commit(repo, "pysandboxes/x.py")
    result = _checked(repo, code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [code]


def test_a_changelog_commit_adds_the_commit_below(repo: Path) -> None:
    code = _commit(repo, "pysandboxes/x.py")
    release = _commit(repo, "CHANGELOG.md")
    assert _checked(repo, release).stdout.split() == [release, code]


def test_consecutive_documentation_commits_are_all_walked(repo: Path) -> None:
    code = _commit(repo, "pysandboxes/x.py")
    changelog = _commit(repo, "CHANGELOG.md")
    wiki = _commit(repo, "wiki/x.md")
    assert _checked(repo, wiki).stdout.split() == [wiki, changelog, code]


def test_a_commit_touching_code_and_documentation_stops_there(repo: Path) -> None:
    _commit(repo, "pysandboxes/x.py")
    mixed = _commit(repo, "CHANGELOG.md", "pysandboxes/x.py")
    assert _checked(repo, mixed).stdout.split() == [mixed]


def test_a_root_documentation_commit_stops_at_the_root(repo: Path) -> None:
    root = _commit(repo, "CHANGELOG.md")
    result = _checked(repo, root)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [root]
