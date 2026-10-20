# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``dir_fd`` resolution when ``/proc`` is not mounted (``unshare.proc=none``).

The guard then resolves a descriptor from the path recorded when ``os.open`` returned it, instead of
reading ``/proc/self/fd/N``.
"""

from collections.abc import Iterator
import os
import shutil
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, guard_files
from pysandboxes.guard_files import _dir_fd_path, _remember_dir_fd, _wrap_os_open
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import _deactivate_all_rules, activate_guard_files_rules

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="resolves descriptors through /proc on Linux")


@pytest.fixture(autouse=True)
def no_proc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(guard_files, "_proc_fd_usable", False)
    monkeypatch.setattr(guard_files, "_tracked_dir_fds", {})
    yield
    _deactivate_all_rules()


def test_a_directory_opened_through_the_guard_is_resolved_without_proc(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    fd = _wrap_os_open(os.open)(str(tmp_path), os.O_RDONLY)
    try:
        assert _dir_fd_path("f.txt", fd) == str(tmp_path / "f.txt")
    finally:
        os.close(fd)


def test_a_directory_opened_relative_to_a_tracked_one_is_tracked(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_open(os.open)
    top = wrapped(str(tmp_path), os.O_RDONLY)
    sub = wrapped("sub", os.O_RDONLY, dir_fd=top)
    try:
        assert _dir_fd_path("f.txt", sub) == str(tmp_path / "sub" / "f.txt")
    finally:
        os.close(sub)
        os.close(top)


def test_a_descriptor_not_opened_through_the_guard_is_denied_with_a_message_about_proc(tmp_path: Path) -> None:
    opened = os.open(str(tmp_path), os.O_RDONLY)
    fd = os.dup(opened)
    try:
        with pytest.raises(RuleFileNotFoundError, match="unshare.proc"):
            _dir_fd_path("f.txt", fd)
    finally:
        os.close(fd)
        os.close(opened)


def test_a_descriptor_number_given_to_another_file_is_denied(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        guard_files._tracked_dir_fds[fd] = (0, 0, str(other))
        with pytest.raises(RuleFileNotFoundError):
            _dir_fd_path("f.txt", fd)
    finally:
        os.close(fd)


def test_a_file_is_not_tracked(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    fd = os.open(str(tmp_path / "f.txt"), os.O_RDONLY)
    try:
        _remember_dir_fd(fd, str(tmp_path / "f.txt"), None)
        assert fd not in guard_files._tracked_dir_fds
    finally:
        os.close(fd)


def test_rmtree_of_a_relative_path_works_without_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = tmp_path / "tree"
    (tree / "a" / "b").mkdir(parents=True)
    (tree / "a" / "b" / "f.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])

    shutil.rmtree("tree")

    _deactivate_all_rules()
    assert not tree.exists()


def test_rmtree_stays_confined_without_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "f.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])

    with pytest.raises(OSError):
        shutil.rmtree("tree")

    _deactivate_all_rules()
    assert (tree / "f.txt").exists()
