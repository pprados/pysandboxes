# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of scripts/tag-release.sh, behind make publish-pre-release, publish-patch, publish-minor and publish-final.

Each test runs the script in a throw-away clone of a throw-away bare origin, signing with a throw-away SSH key; the
user's git configuration is kept out, so the tests neither read nor need the maintainer's key.
"""

import datetime
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "tag-release.sh"
CHANGELOG = "# Changelog\n\n## [0.0.0] - 202X-XX-XX\n\n### Added\n- a thing\n\n## [0.0.1] - 2026-01-01\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=_ENV, check=True, capture_output=True, text=True).stdout.strip()


_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "SSH_AUTH_SOCK": "",
}


@pytest.fixture
def work(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    key = tmp_path / "key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t@example.com", "-f", str(key)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "develop", str(origin)], env=_ENV, check=True)
    subprocess.run(["git", "init", "-q", "-b", "develop", str(work)], env=_ENV, check=True)
    for name, value in {
        "user.name": "T",
        "user.email": "t@example.com",
        "gpg.format": "ssh",
        "user.signingkey": str(key),
    }.items():
        _git(work, "config", name, value)
    (tmp_path / "allowed").write_text(f"t@example.com {(tmp_path / 'key.pub').read_text()}")
    (work / "CHANGELOG.md").write_text(CHANGELOG)
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "develop")
    return work


def _release(work: Path, *args: str, answer: str = "y\n") -> subprocess.CompletedProcess[str]:
    env = _ENV
    return subprocess.run(
        [str(SCRIPT), *args], cwd=work, env=env, input=answer, capture_output=True, text=True, check=False
    )


def _origin_tags(work: Path) -> list[str]:
    return (
        _git(work, "ls-remote", "--tags", "--refs", "origin").split("\n")
        if _git(work, "ls-remote", "--tags", "--refs", "origin")
        else []
    )


def _signed_by_the_key(work: Path, tag: str) -> bool:
    allowed = work.parent / "allowed"
    result = subprocess.run(
        ["git", "-c", f"gpg.ssh.allowedSignersFile={allowed}", "verify-tag", tag],
        cwd=work,
        env=_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _tag_on_origin(work: Path, tag: str) -> bool:
    return any(line.endswith(f"refs/tags/{tag}") for line in _origin_tags(work))


def _commit(work: Path, name: str) -> None:
    (work / name).write_text(name)
    _git(work, "add", name)
    _git(work, "commit", "-q", "-m", name)


# --- pre-releases ---------------------------------------------------------------------------------------------------


def test_a_pre_release_is_signed_on_head_and_pushed_after_develop(work: Path) -> None:
    _commit(work, "feature")
    head = _git(work, "rev-parse", "HEAD")
    result = _release(work, "pre", "0.1.0b1")
    assert result.returncode == 0, result.stderr
    assert _signed_by_the_key(work, "v0.1.0b1")
    assert _git(work, "rev-parse", "v0.1.0b1^{commit}") == head
    assert _tag_on_origin(work, "v0.1.0b1")
    assert _git(work, "rev-parse", "origin/develop") == head
    assert (work / "CHANGELOG.md").read_text() == CHANGELOG


@pytest.mark.parametrize("version", ["", "0.1.0", "v0.1.0b1", "0.1b1", "0.1.0beta1"])
def test_a_pre_release_needs_a_pre_release_version(work: Path, version: str) -> None:
    result = _release(work, "pre", version)
    assert result.returncode != 0
    assert "Usage" in result.stderr
    assert _origin_tags(work) == []


# --- refusals before any change -------------------------------------------------------------------------------------


def test_a_dirty_tree_is_refused(work: Path) -> None:
    (work / "CHANGELOG.md").write_text(CHANGELOG + "dirty\n")
    result = _release(work, "pre", "0.1.0b1")
    assert result.returncode != 0
    assert "not clean" in result.stderr
    assert _git(work, "tag") == ""


def test_another_branch_is_refused(work: Path) -> None:
    _git(work, "checkout", "-q", "-b", "feature")
    result = _release(work, "pre", "0.1.0b1")
    assert result.returncode != 0
    assert "'develop' branch" in result.stderr
    assert _git(work, "tag") == ""


def test_develop_behind_origin_is_refused(work: Path) -> None:
    _commit(work, "pushed")
    _git(work, "push", "-q", "origin", "develop")
    _git(work, "reset", "-q", "--hard", "HEAD~1")
    result = _release(work, "patch")
    assert result.returncode != 0
    assert "behind or has diverged" in result.stderr
    assert _git(work, "tag") == ""
    assert (work / "CHANGELOG.md").read_text() == CHANGELOG


def test_an_existing_tag_is_refused(work: Path) -> None:
    _git(work, "tag", "v0.1.0b1")
    result = _release(work, "pre", "0.1.0b1")
    assert result.returncode != 0
    assert "already exists" in result.stderr


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_a_declined_or_missing_confirmation_tags_nothing(work: Path, answer: str) -> None:
    result = _release(work, "minor", answer=answer)
    assert result.returncode != 0
    assert "Nothing tagged" in result.stderr
    assert _git(work, "tag") == ""
    assert _git(work, "log", "-1", "--format=%s") == "init"


def test_the_diff_since_the_last_tag_is_shown_before_the_question(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.1.0b1")
    (work / "pysandboxes").mkdir()
    _commit(work, "pysandboxes/new.py")
    result = _release(work, "pre", "0.1.0b2", answer="n\n")
    assert "Changes since v0.1.0b1" in result.stdout
    assert "pysandboxes/new.py" in result.stdout


# --- final versions -------------------------------------------------------------------------------------------------


def test_patch_bumps_the_last_final_tag_ignoring_newer_pre_releases(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.0.1")
    _commit(work, "beta")
    _git(work, "tag", "-m", "x", "v0.1.0b5")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch")
    assert result.returncode == 0, result.stderr
    assert _tag_on_origin(work, "v0.0.2")


def test_minor_without_any_final_tag_starts_from_zero(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.1.0b5")
    result = _release(work, "minor")
    assert result.returncode == 0, result.stderr
    assert _tag_on_origin(work, "v0.1.0")


def test_a_final_version_dates_the_changelog_and_leaves_the_next_entry_to_the_next_merge(work: Path) -> None:
    before = datetime.date.today()
    result = _release(work, "minor")
    assert result.returncode == 0, result.stderr
    after = datetime.date.today()
    tagged = _git(work, "show", "v0.1.0:CHANGELOG.md")
    today = next((d.isoformat() for d in (after, before) if f"## [0.1.0] - {d.isoformat()}" in tagged), "")
    assert today, tagged
    assert "## [0.0.0] - 202X-XX-XX" not in tagged
    assert _git(work, "log", "-1", "--format=%s", "v0.1.0") == "chore(release): v0.1.0"
    assert (work / "CHANGELOG.md").read_text() == tagged + "\n"
    assert _git(work, "rev-parse", "origin/develop") == _git(work, "rev-parse", "HEAD")
    assert _git(work, "rev-parse", "v0.1.0^{commit}") == _git(work, "rev-parse", "HEAD")
    assert _signed_by_the_key(work, "v0.1.0")
    allowed = f"gpg.ssh.allowedSignersFile={work.parent / 'allowed'}"
    assert _git(work, "-c", allowed, "log", "-1", "--format=%G?", "HEAD") == "G"


def test_final_tags_the_version_given(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.0.2")
    _commit(work, "feature")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "final", "0.5.0")
    assert result.returncode == 0, result.stderr
    assert _tag_on_origin(work, "v0.5.0")
    assert "## [0.5.0] - " in _git(work, "show", "v0.5.0:CHANGELOG.md")


@pytest.mark.parametrize("version", ["", "0.5", "0.5.0b1", "v0.5.0", "0.0.2", "0.0.1"])
def test_final_refuses_a_malformed_or_not_greater_version(work: Path, version: str) -> None:
    _git(work, "tag", "-m", "x", "v0.0.2")
    result = _release(work, "final", version)
    assert result.returncode != 0
    assert "VERSION=" in result.stderr
    assert _git(work, "tag") == "v0.0.2"
    assert _origin_tags(work) == []


def test_a_later_final_version_keeps_the_entry_lines_with_its_changes_when_no_llm_answers(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.0.1")
    _git(work, "commit", "-q", "--allow-empty", "-m", "feat(guard): deny by default")
    _git(work, "commit", "-q", "--allow-empty", "-m", "ci: not for users")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch")
    assert result.returncode == 0, result.stderr
    entry = _git(work, "show", "v0.0.2:CHANGELOG.md").split("## [0.0.2]")[1].split("## [0.0.1]")[0]
    assert entry.count("- a thing") == 1
    assert entry.index("- a thing") < entry.index("- Deny by default")
    assert "not for users" not in entry
    assert "- Deny by default" in result.stdout


def test_a_later_final_version_replaces_the_entry_with_the_llm_synthesis(work: Path, tmp_path: Path) -> None:
    fake = tmp_path / "fake-llm"
    fake.write_text("#!/usr/bin/env bash\ncat >/dev/null\nprintf '### Added\\n- A thing, now denied by default\\n'\n")
    fake.chmod(0o755)
    _git(work, "tag", "-m", "x", "v0.0.1")
    _git(work, "commit", "-q", "--allow-empty", "-m", "feat(guard): deny by default")
    _git(work, "push", "-q", "origin", "develop")
    result = subprocess.run(
        [str(SCRIPT), "patch"],
        cwd=work,
        env={**_ENV, "CHANGELOG_LLM": str(fake)},
        input="y\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    entry = _git(work, "show", "v0.0.2:CHANGELOG.md").split("## [0.0.2]")[1].split("## [0.0.1]")[0]
    assert entry.split("\n", 1)[1].strip() == "### Added\n- A thing, now denied by default"


def test_the_first_final_version_keeps_the_hand_written_entry_alone(work: Path) -> None:
    _git(work, "commit", "-q", "--allow-empty", "-m", "feat(guard): deny by default")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch")
    assert result.returncode == 0, result.stderr
    assert "Deny by default" not in _git(work, "show", "v0.0.1:CHANGELOG.md")


def test_a_declined_final_version_leaves_the_changelog_untouched(work: Path) -> None:
    _git(work, "tag", "-m", "x", "v0.0.1")
    _git(work, "commit", "-q", "--allow-empty", "-m", "fix: load the filter")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch", answer="n\n")
    assert result.returncode != 0
    assert (work / "CHANGELOG.md").read_text() == CHANGELOG
    assert _git(work, "status", "--porcelain") == ""


def test_the_last_line_names_the_index_of_the_release_kind(work: Path) -> None:
    final = _release(work, "minor")
    assert final.returncode == 0, final.stderr
    assert "Approve the pypi deployment" in final.stdout
    _commit(work, "feature")
    pre = _release(work, "pre", "0.2.0b1")
    assert pre.returncode == 0, pre.stderr
    assert "Approve the testpypi deployment" in pre.stdout


def test_a_final_version_needs_the_open_changelog_entry(work: Path) -> None:
    (work / "CHANGELOG.md").write_text(CHANGELOG.replace("## [0.0.0] - 202X-XX-XX", "## [0.0.9] - 2026-02-02"))
    _git(work, "commit", "-q", "-am", "dated")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch")
    assert result.returncode != 0
    assert "[0.0.0]" in result.stderr
    assert _git(work, "tag") == ""


def test_an_unknown_mode_is_refused(work: Path) -> None:
    result = _release(work, "major")
    assert result.returncode != 0
    assert "Usage" in result.stderr


def _reject_pushes(work: Path) -> None:
    hook = work.parent / "origin.git" / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)


def test_a_final_release_whose_develop_push_fails_says_how_to_recover(work: Path) -> None:
    _commit(work, "unpushed")
    unpushed = _git(work, "rev-parse", "HEAD")
    _reject_pushes(work)
    result = _release(work, "minor")
    assert result.returncode != 0
    assert "git tag -d v0.1.0" in result.stderr
    assert f"git reset --hard {unpushed}" in result.stderr
    assert "reset --hard origin/develop" not in result.stderr
    assert _git(work, "merge-base", "--is-ancestor", unpushed, "HEAD") == ""
    assert _origin_tags(work) == []


def test_a_pre_release_whose_develop_push_fails_says_how_to_recover(work: Path) -> None:
    _commit(work, "feature")
    unpushed = _git(work, "rev-parse", "HEAD")
    _reject_pushes(work)
    result = _release(work, "pre", "0.1.0b1")
    assert result.returncode != 0
    assert "git tag -d v0.1.0b1" in result.stderr
    assert "git reset" not in result.stderr
    assert _git(work, "rev-parse", "HEAD") == unpushed
    assert _origin_tags(work) == []


def test_a_final_version_refuses_a_duplicated_open_entry(work: Path) -> None:
    (work / "CHANGELOG.md").write_text(CHANGELOG + "\n## [0.0.0] - 202X-XX-XX\n")
    _git(work, "commit", "-q", "-am", "twice")
    _git(work, "push", "-q", "origin", "develop")
    result = _release(work, "patch")
    assert result.returncode != 0
    assert "[0.0.0]" in result.stderr
    assert _git(work, "tag") == ""


MAKEFILE = Path(__file__).parents[2] / "Makefile"


def _recipe(target: str) -> list[str]:
    lines = MAKEFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line.strip())
    return recipe


def test_the_publish_targets_call_the_script() -> None:
    assert _recipe("publish-pre-release") == ['@scripts/tag-release.sh pre "$(VERSION)"']
    for bump in ("patch", "minor"):
        recipe = _recipe(f"publish-{bump}")
        assert recipe[-1] == f"@scripts/tag-release.sh {bump}"
    assert _recipe("publish-final")[-1] == '@scripts/tag-release.sh final "$(VERSION)"'


def test_the_final_targets_have_no_lock_left() -> None:
    for bump in ("patch", "minor"):
        assert _recipe(f"publish-{bump}") == ["$(MAKE) release", f"@scripts/tag-release.sh {bump}"]
    assert _recipe("publish-final") == ["$(MAKE) release", '@scripts/tag-release.sh final "$(VERSION)"']
    assert "RELEASE_FINAL" not in SCRIPT.read_text()


def test_release_no_longer_uploads() -> None:
    assert "uv publish" not in "\n".join(_recipe("release"))
    assert MAKEFILE.read_text().count("get-new-version") == 0
