# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/verify-release-tag.sh, the first job of release.yml."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "verify-release-tag.sh"
EMAIL = "maintainer@example.com"


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    # The developer's global config may sign every commit with their own key.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _key(tmp_path: Path, name: str) -> Path:
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], check=True)
    return key


def _tag(repo: Path, name: str, key: Path | None) -> None:
    if key is None:
        _git(repo, "tag", "-a", "-m", f"Release {name}", name)
    else:
        _git(repo, "-c", f"user.signingkey={key}", "tag", "-s", "-m", f"Release {name}", name)


def _verify(repo: Path, ref: str, signers: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), ref],
        cwd=repo,
        env={**os.environ, "ALLOWED_SIGNERS": signers},
        capture_output=True,
        text=True,
    )


def _signers(key: Path) -> str:
    return f"{EMAIL} {Path(f'{key}.pub').read_text().strip()}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    _git(repo, "config", "user.email", EMAIL)
    _git(repo, "config", "user.name", "Maintainer")
    _git(repo, "config", "gpg.format", "ssh")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    return repo


@pytest.fixture
def key(tmp_path: Path) -> Path:
    return _key(tmp_path, "maintainer")


@pytest.mark.parametrize("tag", ["v0.1.0a1", "v0.1.0b1", "v1.20.3rc12"])
def test_signed_prerelease_on_develop_passes(repo: Path, key: Path, tag: str) -> None:
    _tag(repo, tag, key)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

    result = _verify(repo, f"refs/tags/{tag}", _signers(key))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"version={tag[1:]}", f"sha={sha}"]


def test_unsigned_annotated_tag_fails(repo: Path, key: Path) -> None:
    _tag(repo, "v0.1.0b1", None)

    assert _verify(repo, "refs/tags/v0.1.0b1", _signers(key)).returncode != 0


def test_tag_signed_by_unlisted_key_fails(repo: Path, key: Path, tmp_path: Path) -> None:
    _tag(repo, "v0.1.0b1", _key(tmp_path, "intruder"))

    assert _verify(repo, "refs/tags/v0.1.0b1", _signers(key)).returncode != 0


@pytest.mark.parametrize(
    "tag", ["v0.1.0", "v0.1.0-rc1", "v0.1.0.dev1", "v0.1.0b", "0.1.0b1", "v0.1b1", "v0.1.0b1.post1"]
)
def test_other_tag_names_are_refused(repo: Path, key: Path, tag: str) -> None:
    _tag(repo, tag, key)

    result = _verify(repo, f"refs/tags/{tag}", _signers(key))

    assert result.returncode != 0
    assert "final release not enabled yet" in result.stderr


def test_tag_off_develop_fails(repo: Path, key: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "side")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "not on develop")
    _tag(repo, "v0.1.0b1", key)

    result = _verify(repo, "refs/tags/v0.1.0b1", _signers(key))

    assert result.returncode != 0
    assert "not on develop" in result.stderr


def test_empty_allowed_signers_fails(repo: Path, key: Path) -> None:
    _tag(repo, "v0.1.0b1", key)

    result = _verify(repo, "refs/tags/v0.1.0b1", "")

    assert result.returncode != 0
    assert "RELEASE_ALLOWED_SIGNERS" in result.stderr


def test_branch_ref_is_refused(repo: Path, key: Path) -> None:
    result = _verify(repo, "refs/heads/develop", _signers(key))

    assert result.returncode != 0
    assert "not a tag" in result.stderr
