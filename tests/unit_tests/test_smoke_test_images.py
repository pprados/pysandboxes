# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/smoke-test-images.sh, run by the images job of release.yml before any push."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "smoke-test-images.sh"
VERSION = "0.1.0b5"
IMAGES = ["python-sb", "python-sb-landlock", "python-sb-unshare", "python-sb-bwrap", "python-sb-qemu"]

# Stands for docker: logs `run --rm <image> <command...>`; prints the version held in $FAKE_DIR/version-<image>
# (else $FAKE_VERSION) for the importlib.metadata probe; fails when "<image> <command>" is listed in $FAKE_DIR/broken.
FAKE_DOCKER = """#!/usr/bin/env bash
shift 2
image=${1%%:*}; shift
printf '%s %s\\n' "$image" "$*" >>"$FAKE_DIR/calls"
if grep -qxF "$image $1" "$FAKE_DIR/broken" 2>/dev/null; then exit 1; fi
if [[ $1 == python && $2 == -c ]]; then
    cat "$FAKE_DIR/version-$image" 2>/dev/null || echo "$FAKE_VERSION"
fi
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return tmp_path


def _smoke(fake: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "FAKE_VERSION": VERSION,
    }
    return subprocess.run([str(SCRIPT), VERSION, "3.13"], env=env, capture_output=True, text=True, check=False)


def _calls(fake: Path) -> list[str]:
    return (fake / "calls").read_text().splitlines()


def test_five_sound_images_pass(fake: Path) -> None:
    assert _smoke(fake).returncode == 0


def test_every_image_is_probed_for_its_version_and_its_cli(fake: Path) -> None:
    _smoke(fake)
    calls = _calls(fake)
    for image in IMAGES:
        assert any(c.startswith(f"{image} python -c") and "importlib.metadata" in c for c in calls)
        assert f"{image} python-sb --help" in calls


def test_each_provider_image_runs_its_own_binary(fake: Path) -> None:
    _smoke(fake)
    calls = _calls(fake)
    assert "python-sb-unshare unshare --version" in calls
    assert "python-sb-bwrap bwrap --version" in calls
    assert "python-sb-qemu qemu-system-x86_64 --version" in calls
    assert any(c.startswith("python-sb-qemu sh -c") and "PYSANDBOXES_VM_IMAGES_DIR" in c for c in calls)


def test_an_image_holding_another_version_fails(fake: Path) -> None:
    (fake / "version-python-sb-bwrap").write_text("0.1.0b4\n")
    result = _smoke(fake)
    assert result.returncode == 1
    assert "python-sb-bwrap" in result.stdout


@pytest.mark.parametrize(
    "broken",
    ["python-sb-bwrap bwrap", "python-sb-unshare unshare", "python-sb-qemu qemu-system-x86_64", "python-sb-qemu sh"],
)
def test_a_missing_provider_binary_fails(fake: Path, broken: str) -> None:
    (fake / "broken").write_text(broken + "\n")
    assert _smoke(fake).returncode != 0
