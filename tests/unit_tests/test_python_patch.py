# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/python-patch.sh, which reads the Python patch held by python:<minor>-slim."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "python-patch.sh"

# Stands for docker: `pull` logs its image; `image inspect` prints the environment of the image, from $FAKE_ENV.
FAKE_DOCKER = """#!/usr/bin/env bash
if [[ $1 == pull ]]; then echo "${@: -1}" >>"$FAKE_DIR/pulled"; exit 0; fi
printf '%b' "$FAKE_ENV"
"""


def _patch(tmp_path: Path, minor: str, env: str) -> subprocess.CompletedProcess[str]:
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return subprocess.run(
        [str(SCRIPT), minor],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CONTAINER_CMD": str(docker), "FAKE_DIR": str(tmp_path), "FAKE_ENV": env},
    )


def test_the_patch_is_read_from_the_pulled_slim_image(tmp_path: Path) -> None:
    result = _patch(tmp_path, "3.13", "PATH=/usr/local/bin\\nPYTHON_VERSION=3.13.2\\nLANG=C.UTF-8\\n")
    assert result.returncode == 0
    assert result.stdout == "3.13.2\n"
    assert (tmp_path / "pulled").read_text() == "python:3.13-slim\n"


@pytest.mark.parametrize("env", ["PATH=/usr/local/bin\\n", "PYTHON_VERSION=3.12.9\\n", "PYTHON_VERSION=3.13.0rc1\\n"])
def test_an_image_without_a_patch_of_this_minor_is_refused(tmp_path: Path, env: str) -> None:
    result = _patch(tmp_path, "3.13", env)
    assert result.returncode == 1
    assert result.stdout == ""


def test_a_dot_in_the_minor_matches_only_a_dot(tmp_path: Path) -> None:
    assert _patch(tmp_path, "3.1", "PYTHON_VERSION=301.5\\n").returncode == 1


@pytest.mark.parametrize("minor", ["", "3", "3.13.2", "latest"])
def test_an_unexpected_minor_is_refused_before_any_pull(tmp_path: Path, minor: str) -> None:
    result = _patch(tmp_path, minor, "PYTHON_VERSION=3.13.2\\n")
    assert result.returncode == 1
    assert not (tmp_path / "pulled").exists()
