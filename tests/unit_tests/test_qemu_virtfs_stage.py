# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for staging the Python execution trees before -virtfs."""

import os
from pathlib import Path

import pytest

from pysandboxes.remote.qemu_sse_daemon import _stage_exec_virtfs_mounts, _stage_overlay_etc_expose_mount


def _python_tree(root: Path) -> Path:
    bin_dir = root / "py" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3.13").write_text("interpreter")
    (bin_dir / "python3").symlink_to("python3.13")
    return bin_dir


def test_a_child_of_a_staged_mount_keeps_its_symlinks(tmp_path: Path) -> None:
    """A parent is staged before its child: the child's symlinks are already there."""
    bin_dir = _python_tree(tmp_path / "host")
    run = tmp_path / "run"
    run.mkdir()
    specs = [
        ("pysb_exec_0", bin_dir.parent, str(bin_dir.parent)),
        ("pysb_exec_1", bin_dir, str(bin_dir)),
    ]

    _stage_exec_virtfs_mounts(run, specs)

    staged_bin = specs[1][1]
    assert (staged_bin / "python3").is_symlink()
    assert (staged_bin / "python3").resolve().read_text() == "interpreter"


def test_the_same_tree_mounted_twice_is_staged_once(tmp_path: Path) -> None:
    bin_dir = _python_tree(tmp_path / "host")
    run = tmp_path / "run"
    run.mkdir()
    specs = [("pysb_exec_0", bin_dir, str(bin_dir)), ("pysb_exec_1", bin_dir, str(bin_dir))]

    _stage_exec_virtfs_mounts(run, specs)

    assert specs[0][1] == specs[1][1]
    assert (specs[1][1] / "python3").is_symlink()


skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")


@skip_as_root
def test_an_unreadable_file_is_left_out_of_an_exec_tree(tmp_path: Path) -> None:
    """The guest could not read it through a direct 9p mount either."""
    bin_dir = _python_tree(tmp_path / "host")
    secret = bin_dir / "root-only.cfg"
    secret.write_text("secret")
    secret.chmod(0)
    run = tmp_path / "run"
    run.mkdir()
    specs = [("pysb_exec_0", bin_dir, str(bin_dir))]

    try:
        _stage_exec_virtfs_mounts(run, specs)
    finally:
        secret.chmod(0o600)

    assert (specs[0][1] / "python3.13").read_text() == "interpreter"
    assert not (specs[0][1] / "root-only.cfg").exists()


@skip_as_root
def test_an_unreadable_file_is_left_out_of_the_etc_mount(tmp_path: Path) -> None:
    etc = tmp_path / "host" / "etc"
    (etc / "cloud").mkdir(parents=True)
    (etc / "hostname").write_text("box")
    secret = etc / "cloud" / "network.cfg"
    secret.write_text("secret")
    secret.chmod(0)
    run = tmp_path / "run"
    run.mkdir()
    specs = [("pysb_0", etc, "/etc")]

    try:
        _stage_overlay_etc_expose_mount(run, specs)
    finally:
        secret.chmod(0o600)

    assert (specs[0][1] / "hostname").read_text() == "box"
    assert not (specs[0][1] / "cloud" / "network.cfg").exists()
