# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Image version lookup must not synchronize uv during unrelated make targets."""

import os
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).parents[2] / "Makefile"


@pytest.fixture
def make_environment(tmp_path: Path) -> dict[str, str]:
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UV_INVOCATIONS"\nprintf "3.13\\n"\n')
    uv.chmod(0o755)
    for name in ("Dockerfile", ".make-dist"):
        (tmp_path / name).touch()
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "UV_INVOCATIONS": str(tmp_path / "uv.log")}
    env.pop("PYTHON_VERSION", None)
    env.pop("MAKEFLAGS", None)
    return env


def _dry_run(target: str, tmp_path: Path, env: dict[str, str], *arguments: str) -> str:
    return subprocess.run(
        ["make", "-n", "-f", str(MAKEFILE), "-o", ".make-dist", target, *arguments],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout


def _make_variable(name: str, tmp_path: Path, env: dict[str, str]) -> str:
    target = f"print-variable: ; @printf '%s\\n' '$({name})'"
    return subprocess.run(
        ["make", "-s", "-f", str(MAKEFILE), "--eval", target, "print-variable"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()


def test_help_does_not_run_uv(tmp_path: Path, make_environment: dict[str, str]) -> None:
    _dry_run("help", tmp_path, make_environment)
    assert not (tmp_path / "uv.log").exists()


def test_image_build_uses_uv_python_version(tmp_path: Path, make_environment: dict[str, str]) -> None:
    command = _dry_run(".make-build-image-base", tmp_path, make_environment)
    assert "--build-arg PYTHON_VERSION=3.13" in command
    assert "-t python-sb:3.13" in command


def test_qemu_microvm_sample_targets_run_every_sample_with_a_guest_pki_made_empty(
    tmp_path: Path, make_environment: dict[str, str]
) -> None:
    assert _make_variable("SAMPLE_QEMU_MICROVM_EMPTY_PATHS", tmp_path, make_environment) == "/etc/pki"
    assert "crewai" in _make_variable("SAMPLES", tmp_path, make_environment).split()


def test_qemu_microvm_sample_targets_do_not_drop_guest_missing_pki(
    tmp_path: Path, make_environment: dict[str, str]
) -> None:
    paths = _make_variable("SAMPLE_QEMU_MICROVM_OPTIONAL_PATHS", tmp_path, make_environment).split(",")
    assert paths == ["/etc/ssl", "/etc/ca-certificates", "/usr/share/ca-certificates"]
