# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/image-tags.sh, which lists the Docker Hub tags the images.yml workflow pushes."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "image-tags.sh"
DEFAULT = "3.14"


def _tags(version: str, patch: str = "3.14.1") -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), version, patch, DEFAULT], capture_output=True, text=True, check=False)


@pytest.mark.parametrize("version", ["0.1.0a1", "0.1.0b8", "1.2.3rc2"])
def test_a_pre_release_gets_only_the_prefixed_tags(version: str) -> None:
    result = _tags(version)
    assert result.returncode == 0
    assert result.stdout.split() == [f"3.14.1-sb{version}", f"3.14-sb{version}", f"sb{version}"]


def test_a_final_release_also_moves_latest_and_the_python_tags() -> None:
    assert _tags("1.2.3").stdout.split() == [
        "3.14.1-sb1.2.3",
        "3.14-sb1.2.3",
        "sb1.2.3",
        "3.14.1",
        "3.14",
        "3",
        "latest",
    ]


def test_another_python_leaves_the_plain_version_3_and_latest_to_the_default() -> None:
    assert _tags("1.2.3", "3.13.2").stdout.split() == ["3.13.2-sb1.2.3", "3.13-sb1.2.3", "3.13.2", "3.13"]
    assert _tags("0.1.0b8", "3.11.9").stdout.split() == ["3.11.9-sb0.1.0b8", "3.11-sb0.1.0b8"]


def test_a_python_version_never_looks_like_a_pysandboxes_version() -> None:
    tags = _tags("3.13.2", "3.13.2").stdout.split()
    assert tags[:2] == ["3.13.2-sb3.13.2", "3.13-sb3.13.2"]
    assert "3.13.2" in tags and "sb3.13.2" not in tags


@pytest.mark.parametrize("version", ["", "latest", "1.2", "v1.2.3", "sb1.2.3", "1.2.3.post1", "1.2.3b"])
def test_an_unexpected_version_is_refused(version: str) -> None:
    result = _tags(version)
    assert result.returncode == 1
    assert result.stdout == ""


@pytest.mark.parametrize("patch", ["", "3.14", "3", "3.14.1rc1", "py3.14.1"])
def test_a_python_minor_or_pre_release_is_refused(patch: str) -> None:
    result = _tags("1.2.3", patch)
    assert result.returncode == 1
    assert result.stdout == ""
