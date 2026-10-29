# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The mount specs of the QEMU guest once the execution trees are staged: merging, rebasing, copy failures."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.remote import qemu_sse_daemon as qsd

Spec = tuple[str, Path, str]


def test_a_mount_list_without_a_staged_tree_is_left_as_it_is() -> None:
    specs: list[Spec] = [("pysb_1", Path("/host/a"), "/app")]

    qsd._merge_staged_virtfs_into_expose_mounts(specs)

    assert specs == [("pysb_1", Path("/host/a"), "/app")]


def test_an_expose_mount_follows_the_staged_tree_and_the_duplicate_exec_mount_goes() -> None:
    specs: list[Spec] = [
        ("pysb_exec_0", Path("/stage/app"), "/app"),
        ("pysb_1", Path("/host/app"), "/app/"),
        ("pysb_other", Path("/host/other"), "/other"),
        ("pysb_exec_1", Path("/stage/lib"), "/lib"),
    ]

    qsd._merge_staged_virtfs_into_expose_mounts(specs)

    assert specs == [
        ("pysb_1", Path("/stage/app"), "/app/"),
        ("pysb_other", Path("/host/other"), "/other"),
        ("pysb_exec_1", Path("/stage/lib"), "/lib"),
    ]


def test_an_expose_mount_of_another_path_keeps_its_host() -> None:
    specs: list[Spec] = [("pysb_exec_0", Path("/stage/app"), "/app"), ("pysb_2", Path("/host/data"), "/data")]

    qsd._merge_staged_virtfs_into_expose_mounts(specs)

    assert specs == [("pysb_exec_0", Path("/stage/app"), "/app"), ("pysb_2", Path("/host/data"), "/data")]


def test_nothing_is_rebased_without_an_app_expose_mount() -> None:
    specs: list[Spec] = [("pysb_1", Path("/app/tmp"), "/app/tmp")]

    qsd._rebase_file_expose_hosts_under_staged_app(specs)

    assert specs == [("pysb_1", Path("/app/tmp"), "/app/tmp")]


def test_the_children_of_app_move_under_the_staged_app() -> None:
    staged = Path("/stage/app")
    specs: list[Spec] = [
        ("pysb_1", staged, "/app"),
        ("pysb_2", Path("/app/tmp"), "/app/tmp"),
        ("pysb_3", Path("/elsewhere/data"), "/data"),
        ("pysb_exec_0", Path("/app/bin"), "/app/bin"),
        ("pysb_x", Path("/app/x"), "/app/x"),
    ]

    qsd._rebase_file_expose_hosts_under_staged_app(specs)

    assert specs == [
        ("pysb_1", staged, "/app"),
        ("pysb_2", Path("/stage/app/tmp"), "/app/tmp"),
        ("pysb_3", Path("/elsewhere/data"), "/data"),
        ("pysb_exec_0", Path("/app/bin"), "/app/bin"),
        ("pysb_x", Path("/app/x"), "/app/x"),
    ]


def test_a_relative_guest_path_is_not_staged(tmp_path: Path) -> None:
    host = tmp_path / "tree"
    host.mkdir()
    specs: list[Spec] = [("pysb_exec_0", host, "relative/path")]

    qsd._stage_exec_virtfs_mounts(tmp_path / "temp", specs)

    assert specs == [("pysb_exec_0", host, "relative/path")]


def test_a_missing_exec_tree_is_skipped_with_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    specs: list[Spec] = [("pysb_exec_0", tmp_path / "absent", "/opt/tool")]

    with caplog.at_level("WARNING"):
        qsd._stage_exec_virtfs_mounts(tmp_path / "temp", specs)

    assert specs == [("pysb_exec_0", tmp_path / "absent", "/opt/tool")]
    assert "skip missing path" in caplog.text


def test_an_exec_file_is_copied_under_the_stage_and_the_mount_points_there(tmp_path: Path) -> None:
    tool = tmp_path / "tool"
    tool.write_text("#!/bin/sh\n")
    specs: list[Spec] = [("pysb_exec_0", tool, "/opt/tool")]

    qsd._stage_exec_virtfs_mounts(tmp_path / "temp", specs)

    tag, staged, guest = specs[0]
    assert (tag, guest) == ("pysb_exec_0", "/opt/tool")
    assert staged == (tmp_path / "temp" / "virtfs_stage_exec" / "opt" / "tool").resolve()
    assert staged.read_text() == "#!/bin/sh\n"


def test_a_copy_that_fails_is_logged_and_raised(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tool = tmp_path / "tool"
    tool.write_text("x")
    specs: list[Spec] = [("pysb_exec_0", tool, "/opt/tool")]

    with patch.object(qsd.shutil, "copy2", side_effect=OSError("disk full")):
        with caplog.at_level("ERROR"), pytest.raises(OSError, match="disk full"):
            qsd._stage_exec_virtfs_mounts(tmp_path / "temp", specs)

    assert "copy" in caplog.text and "failed" in caplog.text
    assert specs == [("pysb_exec_0", tool, "/opt/tool")]


# %% The host binaries and libraries the guest bootstrap needs


def _elf(path: Path) -> Path:
    path.write_bytes(qsd._ELF_MAGIC + b"\x00" * 16)
    return path


def test_the_bootstrap_seeds_are_the_elf_programs_found_once(tmp_path: Path) -> None:
    mkdir = _elf(tmp_path / "mkdir")
    script = tmp_path / "sh"
    script.write_text("#!/bin/sh\n")
    broken = tmp_path / "bash"
    broken.symlink_to(tmp_path / "gone")
    alias = tmp_path / "dash"
    alias.symlink_to(mkdir)
    found = {"mkdir": str(mkdir), "sh": str(script), "bash": str(broken), "dash": str(alias), "mount": str(tmp_path)}

    with patch.object(qsd.shutil, "which", side_effect=lambda name: found.get(name)):
        assert qsd._qemu_bootstrap_ldd_seed_executables() == [mkdir.resolve()]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_program_is_not_a_seed(tmp_path: Path) -> None:
    locked = _elf(tmp_path / "mkdir")
    locked.chmod(0)
    try:
        with patch.object(qsd.shutil, "which", side_effect=lambda name: str(locked) if name == "mkdir" else None):
            assert qsd._qemu_bootstrap_ldd_seed_executables() == []
    finally:
        locked.chmod(0o600)


def test_the_guest_libraries_found_on_the_host_are_real_files_listed_once() -> None:
    seeds = qsd._qemu_guest_overlay_compat_so_seeds()

    assert len(set(seeds)) == len(seeds)
    assert all(p.is_file() and p == p.resolve() for p in seeds)


def test_a_library_directory_that_cannot_be_globbed_is_skipped() -> None:
    with patch.object(Path, "glob", side_effect=OSError("denied")):
        seeds = qsd._qemu_guest_overlay_compat_so_seeds()

    assert all("libsystemd-shared" not in p.name for p in seeds)
