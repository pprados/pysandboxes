# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/verify-published.sh, the verify-published job of release.yml."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "verify-published.sh"
VERSION = "0.1.0b5"

# Stands for pip: logs its arguments; fails while $FAKE_DIR/misses counts down, then copies
# $FAKE_DIR/published.whl into the --dest directory.
FAKE_PIP = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DIR/calls"
misses=$(cat "$FAKE_DIR/misses")
if ((misses > 0)); then echo $((misses - 1)) >"$FAKE_DIR/misses"; exit 1; fi
while (($#)); do [[ $1 == --dest ]] && dest=$2; shift; done
cp "$FAKE_DIR/published.whl" "$dest/pysandboxes-0.1.0b5-py3-none-any.whl"
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pip = bin_dir / "pip"
    pip.write_text(FAKE_PIP)
    pip.chmod(0o755)
    (tmp_path / "misses").write_text("0")
    (tmp_path / "built.whl").write_bytes(b"wheel")
    (tmp_path / "published.whl").write_bytes(b"wheel")
    return tmp_path


def _verify(fake: Path, attempts: int = 3) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "ATTEMPTS": str(attempts),
        "INTERVAL": "0",
    }
    return subprocess.run(
        [str(SCRIPT), VERSION, str(fake / "built.whl")], env=env, capture_output=True, text=True, check=False
    )


def _calls(fake: Path) -> list[str]:
    return (fake / "calls").read_text().splitlines()


def test_the_published_wheel_matching_the_built_one_passes(fake: Path) -> None:
    assert _verify(fake).returncode == 0


def test_pip_asks_the_index_for_that_exact_wheel_only(fake: Path) -> None:
    _verify(fake)
    args = _calls(fake)[0].split()
    assert args[:2] == ["download", f"pysandboxes=={VERSION}"]
    assert {"--no-deps", "--no-cache-dir", "--only-binary"} <= set(args)
    assert args[args.index("--index-url") + 1] == "https://test.pypi.org/simple/"


def test_a_different_published_file_fails_at_once(fake: Path) -> None:
    (fake / "published.whl").write_bytes(b"another wheel")
    result = _verify(fake)
    assert result.returncode == 1
    assert "differs" in result.stdout
    assert len(_calls(fake)) == 1


def test_a_file_not_visible_yet_is_retried_until_it_shows(fake: Path) -> None:
    (fake / "misses").write_text("2")
    assert _verify(fake).returncode == 0
    assert len(_calls(fake)) == 3


def test_a_file_never_visible_fails_after_every_attempt(fake: Path) -> None:
    (fake / "misses").write_text("99")
    result = _verify(fake, attempts=3)
    assert result.returncode == 1
    assert "published but not visible yet" in result.stdout
    assert len(_calls(fake)) == 3
