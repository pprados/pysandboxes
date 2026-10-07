# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/refresh-images.sh, which decides what images-refresh.yml rebuilds."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "refresh-images.sh"

# Stands for git: `tag --list` prints $FAKE_DIR/tags.
FAKE_GIT = """#!/usr/bin/env bash
cat "$FAKE_DIR/tags" 2>/dev/null || true
"""
# Stands for docker: python:<minor>-slim holds <minor>.7; a manifest exists when listed in $FAKE_DIR/present.
FAKE_DOCKER = """#!/usr/bin/env bash
case $1 in
pull) exit 0 ;;
image) minor=${@: -1}; minor=${minor#python:}; echo "PYTHON_VERSION=${minor%-slim}.7" ;;
manifest) grep -qxF "$3" "$FAKE_DIR/present" 2>/dev/null ;;
esac
"""


def _refresh(tmp_path: Path, tags: str, present: str = "") -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("git", FAKE_GIT), ("docker", FAKE_DOCKER)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    (tmp_path / "tags").write_text(tags)
    (tmp_path / "present").write_text(present)
    return subprocess.run(
        [str(SCRIPT), "3.13", "3.14"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path)},
    )


def test_without_a_final_release_nothing_is_rebuilt(tmp_path: Path) -> None:
    result = _refresh(tmp_path, "v0.5.0b1\nv0.1.0rc1\n")
    assert result.returncode == 0
    assert result.stdout == "minors=[]\n"


def test_the_latest_final_release_is_chosen_in_version_order(tmp_path: Path) -> None:
    result = _refresh(tmp_path, "v0.9.0\nv0.10.0\nv0.11.0b1\nv0.10.0rc2\n")
    assert result.stdout.splitlines()[0] == "tag=v0.10.0"


def test_only_the_pythons_without_an_image_of_their_newest_patch_are_rebuilt(tmp_path: Path) -> None:
    result = _refresh(tmp_path, "v1.0.0\n", "docker.io/pprados/python-sb-qemu:3.14.7-sb1.0.0\n")
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["tag=v1.0.0", 'minors=["3.13"]']


def test_every_python_is_rebuilt_when_no_image_exists(tmp_path: Path) -> None:
    assert _refresh(tmp_path, "v1.0.0\n").stdout.splitlines()[1] == 'minors=["3.13","3.14"]'


def test_nothing_is_rebuilt_when_every_image_exists(tmp_path: Path) -> None:
    present = "docker.io/pprados/python-sb-qemu:3.13.7-sb1.0.0\ndocker.io/pprados/python-sb-qemu:3.14.7-sb1.0.0\n"
    assert _refresh(tmp_path, "v1.0.0\n", present).stdout.splitlines()[1] == "minors=[]"
