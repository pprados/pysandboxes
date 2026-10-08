# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, RulePermissionError
from pysandboxes.guard_files import _check_alias, _wrap_pathlib_Path_glob
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules

NonePath = Path()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """`ro` and `rw` are exposed, `out` is not. Built before any guard is armed."""
    root = Path(os.path.realpath(tmp_path))
    for d in ("ro", "rw", "out"):
        (root / d).mkdir()
    (root / "ro" / "file.txt").write_text("ro")
    (root / "rw" / "file.txt").write_text("rw")
    (root / "out" / "secret.txt").write_text("secret")
    (root / "out" / "link_to_ro").symlink_to(root / "ro" / "file.txt")
    (root / "ro" / "link_to_out").symlink_to(root / "out" / "secret.txt")
    (root / "ro" / "link_to_rw").symlink_to(root / "rw" / "file.txt")
    (root / "rw" / "link_to_ro").symlink_to(root / "ro" / "file.txt")
    (root / "rw" / ".hidden").mkdir()
    (root / "rw" / ".hidden" / "key").write_text("key")
    return root


def _arm(root: Path, *extra: str) -> None:
    rules = [ConfigLine(f"expose-ro={root / 'ro'}", NonePath, 0), ConfigLine(f"expose-rw={root / 'rw'}", NonePath, 0)]
    rules += [ConfigLine(line, NonePath, 0) for line in extra]
    activate_guard_files_rules(rules)


def test_readlink_of_a_link_outside_the_exposed_directories_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RuleFileNotFoundError):
        os.readlink(tree / "out" / "link_to_ro")


def test_readlink_does_not_reveal_a_target_outside_the_exposed_directories(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RuleFileNotFoundError):
        os.readlink(tree / "ro" / "link_to_out")


def test_readlink_of_an_exposed_link_to_an_exposed_target_works(tree: Path) -> None:
    _arm(tree)
    assert os.readlink(tree / "ro" / "link_to_rw") == str(tree / "rw" / "file.txt")


def test_glob_does_not_list_files_outside_the_exposed_directories(tree: Path) -> None:
    _arm(tree)
    names = {p.name for p in Path(tree / "ro").glob("../*/*")}
    assert "secret.txt" not in names
    assert "file.txt" in names


def test_a_hard_link_to_a_read_only_file_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RulePermissionError):
        os.link(tree / "ro" / "file.txt", tree / "rw" / "hard")
    assert not (tree / "rw" / "hard").exists()


def test_a_relative_ignore_pattern_hides_a_directory_on_the_path(tree: Path) -> None:
    _arm(tree, "ignore=.hidden")
    with pytest.raises(RuleFileNotFoundError):
        open(tree / "rw" / ".hidden" / "key").close()


@pytest.mark.skipif(sys.platform == "win32", reason="no fifo on Windows")
def test_mkfifo_in_a_read_only_directory_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RulePermissionError):
        os.mkfifo(tree / "ro" / "fifo")


@pytest.mark.skipif(sys.platform == "win32", reason="no mknod on Windows")
def test_mknod_in_a_read_only_directory_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RulePermissionError):
        os.mknod(tree / "ro" / "node")


def test_os_open_with_flags_that_are_not_an_int_reaches_os_open(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(TypeError):
        os.open(tree / "rw" / "file.txt", "r")  # type: ignore[arg-type]


def test_removing_a_link_in_a_read_only_directory_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RulePermissionError):
        os.unlink(tree / "ro" / "link_to_rw")
    with pytest.raises(RulePermissionError):
        os.remove(tree / "ro" / "link_to_rw")
    assert (tree / "ro" / "link_to_rw").is_symlink()


def test_moving_a_link_out_of_a_read_only_directory_is_refused(tree: Path) -> None:
    _arm(tree)
    with pytest.raises(RulePermissionError):
        os.rename(tree / "ro" / "link_to_rw", tree / "rw" / "moved")
    with pytest.raises(RulePermissionError):
        os.replace(tree / "ro" / "link_to_rw", tree / "rw" / "moved")


def test_removing_a_link_to_a_read_only_file_from_a_writable_directory_works(tree: Path) -> None:
    _arm(tree)
    os.unlink(tree / "rw" / "link_to_ro")
    assert (tree / "ro" / "file.txt").exists()


def test_glob_restores_the_alias_check_when_the_scan_fails(tree: Path) -> None:
    def failing_glob(self: Any, pattern: str, **kwargs: Any) -> Iterator[Path]:
        raise OSError("scan failed")
        yield self  # pragma: no cover

    _arm(tree)
    glob = _wrap_pathlib_Path_glob(failing_glob)
    with pytest.raises(OSError, match="scan failed"):
        list(glob(tree / "rw", "*"))
    assert _check_alias.get() is True


@pytest.mark.skipif(sys.version_info < (3, 13), reason="recurse_symlinks exists from 3.13")
def test_glob_keeps_case_sensitive_beside_recurse_symlinks(tree: Path) -> None:
    seen: dict[str, Any] = {}

    def recording_glob(self: Any, pattern: str, **kwargs: Any) -> Iterator[Path]:
        seen.update(kwargs)
        return iter(())

    _arm(tree)
    list(_wrap_pathlib_Path_glob(recording_glob)(tree / "rw", "*", case_sensitive=False, recurse_symlinks=True))
    assert seen == {"case_sensitive": False, "recurse_symlinks": True}


def test_relative_ignore_pattern_does_not_match_a_dot_named_ancestor(tmp_path: Path) -> None:
    # G8: the exposed root itself lives under a dot-named ancestor directory. A relative
    # ignore pattern must only be judged against the components below the exposed root,
    # never against ancestors above it.
    root = Path(os.path.realpath(tmp_path)) / "x" / ".p" / "proj"
    root.mkdir(parents=True)
    (root / "ro").mkdir()
    (root / "rw").mkdir()
    (root / "ro" / "file.txt").write_text("ro")
    (root / "rw" / "file.txt").write_text("rw")
    _arm(root, "ignore=.*")
    # The exposed files must still be readable: ".p" is an ancestor, not a path component
    # below either exposed root.
    assert open(root / "ro" / "file.txt").read() == "ro"
    assert open(root / "rw" / "file.txt").read() == "rw"


def test_relative_ignore_pattern_still_hides_matching_names_below_the_root(tree: Path) -> None:
    # Keep the intended behaviour of a relative ignore= pattern.
    (tree / "rw" / ".secrets").mkdir()
    (tree / "rw" / ".secrets" / "key").write_text("key")
    (tree / "rw" / "a").mkdir()
    (tree / "rw" / "a" / ".secrets").mkdir()
    (tree / "rw" / "a" / ".secrets" / "b").write_text("b")
    _arm(tree, "ignore=.secrets")
    with pytest.raises(RuleFileNotFoundError):
        open(tree / "rw" / ".secrets" / "key").close()
    with pytest.raises(RuleFileNotFoundError):
        open(tree / "rw" / "a" / ".secrets" / "b").close()


def test_unlink_with_dir_fd_judges_a_link_on_its_holder_directory(tree: Path) -> None:
    # G18: os.unlink(name, dir_fd=fd) must judge a link exactly like the plain-path form:
    # on the directory holding it (read-only "ro"), not on the realpath-resolved target
    # ("rw", writable). Without the fix this succeeds.
    _arm(tree)
    fd = os.open(tree / "ro", os.O_RDONLY)
    try:
        with pytest.raises(RulePermissionError):
            os.unlink("link_to_rw", dir_fd=fd)
    finally:
        os.close(fd)
    assert (tree / "ro" / "link_to_rw").is_symlink()


def test_remove_with_dir_fd_judges_a_link_on_its_holder_directory(tree: Path) -> None:
    _arm(tree)
    fd = os.open(tree / "ro", os.O_RDONLY)
    try:
        with pytest.raises(RulePermissionError):
            os.remove("link_to_rw", dir_fd=fd)
    finally:
        os.close(fd)
    assert (tree / "ro" / "link_to_rw").is_symlink()


def test_rename_with_src_dir_fd_judges_a_link_on_its_holder_directory(tree: Path) -> None:
    _arm(tree)
    fd = os.open(tree / "ro", os.O_RDONLY)
    try:
        with pytest.raises(RulePermissionError):
            os.rename("link_to_rw", str(tree / "rw" / "moved"), src_dir_fd=fd)
    finally:
        os.close(fd)
    assert (tree / "ro" / "link_to_rw").is_symlink()


def test_readlink_with_dir_fd_checks_the_holder_directory_is_exposed(tree: Path) -> None:
    # G1: os.readlink(path, dir_fd=fd) must check that the directory holding the link is
    # exposed, exactly like the plain-path form. "out" is not exposed.
    _arm(tree)
    fd = os.open(tree / "rw", os.O_RDONLY)
    try:
        with pytest.raises(RuleFileNotFoundError):
            os.readlink("../out/link_to_ro", dir_fd=fd)
    finally:
        os.close(fd)


def test_copytree_ignore_callback_runs_with_the_alias_check_restored(tree: Path) -> None:
    # G10: the user's ignore= callback must not be able to stat paths outside the exposed
    # directories while copytree disables the alias check for its own internal walk.
    import shutil

    from pysandboxes.guard_files import _check_alias

    (tree / "rw" / "srcdir").mkdir()
    (tree / "rw" / "srcdir" / "a.txt").write_text("a")

    seen_during_callback = []

    def ignore(dirpath: str, names: list[str]) -> set[str]:
        seen_during_callback.append(_check_alias.get())
        return set()

    _arm(tree)
    shutil.copytree(tree / "rw" / "srcdir", tree / "rw" / "copied", ignore=ignore)
    assert seen_during_callback
    assert all(seen_during_callback), "ignore= callback ran with the alias check disabled"
