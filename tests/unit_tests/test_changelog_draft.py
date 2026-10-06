# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of scripts/changelog-draft.sh, which drafts the CHANGELOG.md entry of a final version.

The LLM is replaced by a fake command (CHANGELOG_LLM), so the tests never call a model.
"""

import os
import random
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "changelog-draft.sh"
_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=_ENV, check=True, capture_output=True)


def _commit(repo: Path, subject: str) -> None:
    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "develop")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _commit(tmp_path, "feat: before the release")
    _git(tmp_path, "tag", "v0.0.1")
    return tmp_path


def _fake_llm(tmp_path: Path, body: str, code: int = 0) -> str:
    fake = tmp_path / "fake-llm"
    fake.write_text(f"#!/usr/bin/env bash\ncat >{tmp_path / 'llm-input'}\nprintf '%s' '{body}'\nexit {code}\n")
    fake.chmod(0o755)
    return str(fake)


def _draft(repo: Path, llm: str, since: str = "v0.0.1", entry: str | None = None) -> subprocess.CompletedProcess[str]:
    args = [str(SCRIPT), since]
    if entry is not None:
        (repo.parent / "entry.md").write_text(entry)
        args.append(str(repo.parent / "entry.md"))
    return subprocess.run(
        args, cwd=repo, env={**_ENV, "CHANGELOG_LLM": llm}, capture_output=True, text=True, check=False
    )


def _subjects_sent(tmp_path: Path) -> list[str]:
    return (tmp_path / "llm-input").read_text().split("Commit subjects:\n")[1].split("\n")[:-1]


def test_the_entry_lines_and_the_commits_reach_the_llm_together(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "feat(guard): deny by default")
    entry = "\n### Added\n- A note from a merge\n\nA hand-written paragraph.\n"
    result = _draft(repo, _fake_llm(tmp_path, "### Added\n- Merged.\n"), entry=entry)
    assert result.returncode == 0, result.stderr
    sent = (tmp_path / "llm-input").read_text()
    assert sent.startswith("Current entry:\n### Added\n- A note from a merge\n\nA hand-written paragraph.\n\n")
    assert _subjects_sent(tmp_path) == ["feat(guard): deny by default"]
    assert result.stdout == "### Added\n- Merged.\n"


def test_without_a_working_llm_the_entry_is_kept_above_the_commit_list(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "fix: load the filter")
    result = _draft(repo, str(tmp_path / "no-such-command"), entry="\n### Added\n- A note from a merge\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "### Added\n- A note from a merge\n\n### Fixed\n- Load the filter\n"


def test_only_the_user_facing_commits_since_the_tag_reach_the_llm(repo: Path, tmp_path: Path) -> None:
    for subject in (
        "feat(guard): deny by default",
        "fix(bwrap): load the filter",
        "ci: tweak",
        "docs: typo",
        "chore(release): v0.0.2",
        "perf: faster import",
        "test: more",
    ):
        _commit(repo, subject)
    llm = _fake_llm(tmp_path, "### Added\n- Denied by default.\n")
    result = _draft(repo, llm)
    assert result.returncode == 0, result.stderr
    assert _subjects_sent(tmp_path) == [
        "perf: faster import",
        "fix(bwrap): load the filter",
        "feat(guard): deny by default",
    ]
    assert result.stdout == "### Added\n- Denied by default.\n"


def test_nothing_user_facing_prints_nothing_and_skips_the_llm(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "ci: tweak")
    result = _draft(repo, _fake_llm(tmp_path, "### Added\n- x\n"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "llm-input").exists()


@pytest.mark.parametrize(
    "body",
    ["```markdown\n### Added\n- x\n```\n", "Here is the changelog:\n### Added\n- x\n", "## [1.0.0]\n- x\n", ""],
)
def test_an_output_of_the_wrong_shape_falls_back_to_the_commit_list(repo: Path, tmp_path: Path, body: str) -> None:
    _commit(repo, "feat(guard): deny by default")
    _commit(repo, "fix: load the filter")
    result = _draft(repo, _fake_llm(tmp_path, body))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "### Added\n- Deny by default\n\n### Fixed\n- Load the filter\n"
    assert "falls back" in result.stderr


def test_a_failing_llm_falls_back_to_the_commit_list(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "fix!: refuse the old option")
    result = _draft(repo, _fake_llm(tmp_path, "### Fixed\n- ok\n", code=1))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "### Fixed\n- Refuse the old option\n"


def test_a_missing_llm_falls_back_to_the_commit_list(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "perf: faster import")
    result = _draft(repo, str(tmp_path / "no-such-command"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "### Changed\n- Faster import\n"


def test_without_a_previous_tag_the_whole_history_counts(repo: Path, tmp_path: Path) -> None:
    llm = _fake_llm(tmp_path, "### Added\n- x\n")
    assert _draft(repo, llm, since="").returncode == 0
    assert _subjects_sent(tmp_path) == ["feat: before the release"]


@pytest.mark.llm
def test_the_real_llm_drafts_the_changes_since_a_random_older_version() -> None:
    root = SCRIPT.parents[1]

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout

    candidates = [
        tag
        for tag in git("tag", "--merged", "HEAD", "-l", "v*").split()
        if re.search(
            r"^(feat|fix|perf|security)(\(|!|:)", git("log", "--no-merges", "--format=%s", f"{tag}..HEAD"), re.M
        )
    ]
    assert candidates, "no older version with user-facing commits since"
    since = random.choice(candidates)
    # tag-release.sh runs from the maintainer's shell, logged in to claude; pytest-dotenv injects the samples' .env,
    # whose ANTHROPIC_API_KEY would take precedence over that login.
    env = {k: v for k, v in os.environ.items() if k not in ("CHANGELOG_LLM", "ANTHROPIC_API_KEY")}
    result = subprocess.run([str(SCRIPT), since], cwd=root, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "falls back" not in result.stderr, f"since {since}: {result.stderr}"
    assert re.search(r"^### (Added|Changed|Fixed|Security)$", result.stdout, re.M), result.stdout
    assert re.search(r"^- \S", result.stdout, re.M), result.stdout
