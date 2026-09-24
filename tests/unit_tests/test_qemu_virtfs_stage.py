# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for staging the Python execution trees before -virtfs."""

from pathlib import Path

from pysandboxes.remote.qemu_sse_daemon import _stage_exec_virtfs_mounts


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
