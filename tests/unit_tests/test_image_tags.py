# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/image-tags.sh, which lists the Docker Hub tags the images job of release.yml pushes."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "image-tags.sh"
DEFAULT = "3.13"


def _tags(version: str, python: str = DEFAULT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), version, python, DEFAULT], capture_output=True, text=True, check=False)


@pytest.mark.parametrize("version", ["0.1.0a1", "0.1.0b8", "1.2.3rc2"])
def test_a_pre_release_gets_only_the_immutable_tags(version: str) -> None:
    result = _tags(version)
    assert result.returncode == 0
    assert result.stdout.split() == [version, f"{version}-py3.13"]


def test_a_final_release_also_moves_latest_and_the_python_tag() -> None:
    assert _tags("1.2.3").stdout.split() == ["1.2.3", "1.2.3-py3.13", "py3.13", "latest"]


def test_another_python_leaves_the_plain_version_and_latest_to_the_default() -> None:
    assert _tags("1.2.3", "3.14").stdout.split() == ["1.2.3-py3.14", "py3.14"]
    assert _tags("0.1.0b8", "3.11").stdout.split() == ["0.1.0b8-py3.11"]


@pytest.mark.parametrize("version", ["", "latest", "1.2", "v1.2.3", "1.2.3.post1", "1.2.3b"])
def test_an_unexpected_version_is_refused(version: str) -> None:
    result = _tags(version)
    assert result.returncode == 1
    assert result.stdout == ""
