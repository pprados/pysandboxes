import stat
import sys
import time
from pathlib import Path
from typing import Dict

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, RulePermissionError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


def test_os_listdir_filters_ignored_files_and_expose(
    files: Dict[str, Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    entries = os.listdir(files["path"])
    assert "ignore.log" not in entries
    assert "bind_src" in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries

    entries = os.listdir(files["bind_dest"])
    assert "bound_file.txt" in entries

    assert "bound_file.txt" in os.listdir(files["bind_src"])


def test_os_statand_stat_and_lstat(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.stat(files["visible"])
    with pytest.raises(RuleFileNotFoundError):
        assert os.stat(files["ignore"])
    assert os.stat(files["home_link"], follow_symlinks=True)
    assert os.stat(files["bound_file"], follow_symlinks=True)
    assert os.stat(files["bind_dest"], follow_symlinks=True)
    assert os.stat(files["bind_src"], follow_symlinks=True)

    assert os.lstat(files["visible"])
    with pytest.raises(RuleFileNotFoundError):
        assert os.lstat(files["ignore"])
    assert os.lstat(files["home_link"])
    assert os.lstat(files["bound_file"])
    assert os.lstat(files["bind_dest"])

    assert os.lstat(files["bind_src"])


@pytest.mark.skipif(sys.platform != "linux", reason="xattr is Linux-only")
def test_os_listxattr(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.listxattr(files["visible"]) == []

    with pytest.raises(RuleFileNotFoundError):
        os.listxattr(files["ignore"])

    assert os.listxattr(files["bind_src"]) == []


@pytest.mark.skipif(sys.platform != "linux", reason="xattr is Linux-only")
def test_os_xattr(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    os.setxattr(files["visible"], "user.comment", b"comment")
    assert os.getxattr(files["visible"], "user.comment") == b"comment"
    assert os.listxattr(files["visible"]) == ["user.comment"]
    os.removexattr(files["visible"], "user.comment")
    os.setxattr(files["bound_file"], "user.comment", b"comment")
    assert os.getxattr(files["bound_file"], "user.comment") == b"comment"
    assert os.listxattr(files["bound_file"]) == ["user.comment"]
    os.removexattr(files["bound_file"], "user.comment")

    with pytest.raises(RuleFileNotFoundError):
        os.getxattr(files["ignore"], "user.comment")

    with pytest.raises(OSError):
        os.getxattr(files["bind_src"], "user.comment")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows readlink returns \\\\?\\ paths")
def test_os_link_symlink_and_readlink(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.readlink(files["home_link"]) == str(files["visible"])
    assert os.readlink(files["home_link_to_bind_src"]) == str(files["bound_file"])
    assert Path(os.readlink(files["home_link_relative_to_bind_src"])) == Path(files["bound_file"])
    assert os.readlink(files["link_to_bind"]) == str(files["bound_file"])
    assert (
        Path(files["bind_dest"] / os.readlink(files["link_relative_to_bind"])).resolve()
        == Path(files["bind_dest"] / "bound_file.txt").resolve()
    )
    with pytest.raises(RuleFileNotFoundError):
        os.readlink(files["home_link_to_ignore"])

    files["new_link"].unlink(missing_ok=True)
    os.link(files["visible"], files["new_link"])
    assert files["new_link"].exists()
    os.remove(files["new_link"])

    files["new_link_to_bind"].unlink(missing_ok=True)
    os.link(files["bound_file"], files["new_link_to_bind"])
    assert os.path.exists(files["new_link_to_bind"])
    os.unlink(files["new_link_to_bind"])

    with pytest.raises((RuleFileNotFoundError, FileNotFoundError)):
        os.link(files["bind_src"] / "toto", files["new_link"])

    os.symlink(files["visible"], files["new_link"])
    assert files["new_link"].exists()
    assert os.readlink(files["new_link"]) == str(files["visible"])
    os.remove(files["new_link"])

    files["new_link_to_bind"].unlink(missing_ok=True)
    os.symlink(files["visible"], files["new_link_to_bind"])
    assert os.path.exists(files["new_link_to_bind"])
    assert os.readlink(files["new_link_to_bind"]) == str(files["visible"])
    os.unlink(files["new_link_to_bind"])

    files["new_link"].unlink(missing_ok=True)
    os.symlink(files["visible"], files["bind_src"] / "link_in_bind_src")
    assert os.readlink(files["bind_src"] / "link_in_bind_src") == str(files["visible"])
    os.unlink(files["bind_src"] / "link_in_bind_src")

    files["new_link"].unlink(missing_ok=True)
    os.symlink(files["bind_dest"], files["new_link"])
    assert os.path.exists(files["new_link"])


def test_os_remove(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    (files["path"] / "to_remove.txt").write_text("To remove")
    os.remove(files["path"] / "to_remove.txt")

    # Try to remove ignored file
    with pytest.raises(RuleFileNotFoundError):
        os.remove(files["ignore"])

    f = os.open(files["bind_dest"] / "to_remove.txt", os.O_CREAT | os.O_WRONLY)
    try:
        os.write(f, b"To remove")
    finally:
        os.close(f)
    os.remove(files["bind_dest"] / "to_remove.txt")


def test_os_remove_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.remove(files["bound_file"])


def test_os_mkdir_removedirs_and_rmdir(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import shutil

    d = files["path"] / "dir_to_remove"
    if d.exists():
        shutil.rmtree(d)
    os.mkdir(d)
    os.rmdir(d)

    d = files["bind_dest"] / "dir_to_remove"
    if d.exists():
        shutil.rmtree(d)
    os.mkdir(d)
    os.rmdir(d)

    os.mkdir(files["bind_src"] / "dir_to_remove")
    os.rmdir(files["bind_src"] / "dir_to_remove")

    d = files["path"] / "dir_to_remove"
    if d.exists():
        shutil.rmtree(d)
    os.mkdir(d)
    os.removedirs(files["path"] / "dir_to_remove")

    d = files["bind_dest"] / "dir_to_remove"
    if d.exists():
        shutil.rmtree(d)
    os.mkdir(d)
    os.removedirs(files["bind_dest"] / "dir_to_remove")

    os.mkdir(files["bind_src"] / "dir_to_remove")
    os.removedirs(files["bind_src"] / "dir_to_remove")


def test_os_mkdir_removedirs_and_rmdir_refused(
    files: Dict[str, Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    os.rmdir(files["bind_dest"] / "dir_to_remove")

    os.mkdir(files["bind_src"] / "dir_to_remove")
    os.rmdir(files["bind_src"] / "dir_to_remove")

    # The name says "refused", so something must be: files["path"] is exposed
    # by no rule here.
    with pytest.raises(RuleFileNotFoundError):
        os.mkdir(files["path"] / "refused")


def test_os_directory_reads_outside_the_rules_are_denied(
    files: Dict[str, Path],  # noqa: F811
) -> None:
    """chdir, listdir and scandir all refuse a directory no rule exposes.

    Their deny branch had no test: only allowed directories were ever read,
    so a broken wrapper would have exposed the whole host filesystem.
    """
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    outside = files["bind_dest"]

    with pytest.raises(RuleFileNotFoundError):
        os.chdir(outside)
    with pytest.raises(RuleFileNotFoundError):
        os.listdir(outside)
    with pytest.raises(RuleFileNotFoundError):
        list(os.scandir(outside))


def test_os_rename(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io
    import os

    with io.open(files["to_rename"], "w") as f:
        f.write("To rename")
    os.rename(files["to_rename"], files["new_rename"])
    os.unlink(files["new_rename"])

    with io.open(files["bind_to_rename"], "w") as f:
        f.write("To rename")
    os.rename(files["bind_to_rename"], files["new_bind_rename"])
    os.unlink(files["new_bind_rename"])

    with pytest.raises((RuleFileNotFoundError, FileNotFoundError)):
        os.rename(files["bind_src"] / "toto", files["visible"])

    with pytest.raises(RuleFileNotFoundError):
        os.rename(files["ignore"], str(files["ignore"]) + "-back")


def test_os_rename_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.rename(files["to_rename"], files["bound_file"])


def test_os_chdir_and_getcwd(files: Dict[str, Path]) -> None:  # noqa: F811
    import os

    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={os.environ['PWD']}", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    old_dir = os.getcwd()
    os.chdir(files["path"])
    assert str(files["path"]) == os.getcwd()
    os.chdir(files["bind_dest"])
    assert str(files["bind_dest"]) == os.getcwd()
    os.chdir(files["bind_src"])
    assert str(files["bind_src"]) == os.getcwd()
    os.chdir(old_dir)


def test_os_getcwdb(files: Dict[str, Path]) -> None:  # noqa: F811
    import os

    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={os.environ['PWD']}", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    cwd = os.getcwdb()
    assert isinstance(cwd, bytes)
    assert cwd.decode(sys.getfilesystemencoding()) == os.getcwd()


def test_os_open_without_a_mode_uses_the_default_0o777(files: Dict[str, Path]) -> None:  # noqa: F811
    # The wrapper defaulted to 0x777 (0o3567): setgid and sticky, and no write bit for
    # the owner, so Windows made the file read-only and refused to remove it.
    activate_guard_files_rules([ConfigLine(f"expose-rw={files['path']}", Path(), 0)])

    import os

    umask = os.umask(0)
    os.umask(umask)
    target = files["path"] / "default_mode.txt"
    os.close(os.open(target, os.O_CREAT | os.O_WRONLY))
    try:
        if sys.platform == "win32":
            assert os.stat(target).st_mode & 0o200, "created read-only"
        else:
            assert os.stat(target).st_mode & 0o7777 == 0o777 & ~umask
    finally:
        os.remove(target)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot os.open a directory")
def test_os_open_readonly(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    fd = -1
    try:
        fd = os.open(files["visible"], os.O_RDONLY)
    finally:
        if fd != -1:
            os.close(fd)
    try:
        fd = os.open(files["bind_dest"], os.O_RDONLY)
    finally:
        if fd != -1:
            os.close(fd)

    with pytest.raises(RuleFileNotFoundError):
        os.open(files["ignore"], os.O_RDONLY)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot os.open a directory")
def test_os_open_writeonly(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    fd = -1
    try:
        fd = os.open(files["visible"], os.O_WRONLY)
    finally:
        if fd != -1:
            os.close(fd)
    try:
        fd = os.open(files["bind_dest"], os.O_RDONLY)
    finally:
        if fd != -1:
            os.close(fd)

    with pytest.raises(RuleFileNotFoundError):
        os.open(files["ignore"], os.O_RDONLY)


def test_os_open_writeonly_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        fd = -1
        try:
            fd = os.open(files["bind_dest"], os.O_WRONLY)
        finally:
            if fd != -1:
                os.close(fd)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot os.open a directory")
def test_os_open_readwrite(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    fd = -1
    try:
        fd = os.open(files["visible"], os.O_RDWR)
    finally:
        if fd != -1:
            os.close(fd)
    try:
        fd = os.open(files["bind_dest"], os.O_RDONLY)
    finally:
        if fd != -1:
            os.close(fd)


def test_os_open_readwrite_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        fd = -1
        try:
            fd = os.open(files["bind_dest"], os.O_WRONLY)
        finally:
            if fd != -1:
                os.close(fd)


def test_os_access_read_write(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.access(files["path"], os.R_OK | os.W_OK)
    assert os.access(files["visible"], os.R_OK | os.W_OK)
    assert os.access(files["bound_file"], os.R_OK | os.W_OK)
    assert os.access(files["bind_dest"], os.R_OK | os.W_OK)
    assert os.access(files["bind_src"], os.R_OK | os.W_OK)


def test_os_access_outside_the_rules_is_reported_inaccessible(
    files: Dict[str, Path],  # noqa: F811
) -> None:
    """A path no rule exposes must answer False, not the truth.

    Answering for real turns os.access into an existence and permission
    oracle over the whole host filesystem; raising would break the
    documented bool contract every caller relies on.
    """
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.access(files["bind_src"], os.R_OK)
    # Exists on the host, exposed by no rule.
    assert not os.access(files["visible"], os.R_OK)
    # Absent as well: the two answers must not differ, or the oracle is back.
    assert not os.access(files["path"] / "does_not_exist", os.R_OK)


def test_os_access_read_only(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.access(files["path"], os.R_OK | os.W_OK)
    assert os.access(files["visible"], os.R_OK | os.W_OK)
    assert os.access(files["bound_file"], os.R_OK | os.W_OK)
    assert os.access(files["bind_dest"], os.R_OK | os.W_OK)
    assert os.access(files["bind_src"], os.R_OK)
    with pytest.raises((PermissionError, RulePermissionError)):
        with open(files["bound_file"], "a", encoding="utf-8") as f:
            f.write("x")


@pytest.mark.skipif(
    not (sys.platform != "win32" and sys.platform != "linux"),
    reason="requires special os",
)
def test_os_chflags_and_lchflags(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    # UF_NODUMP: a user flag the owner may set; the SF_* system flags need root.
    os.chflags(files["path"], stat.UF_NODUMP)  # type: ignore[attr-defined]
    os.chflags(files["bound_file"], stat.UF_NODUMP)  # type: ignore[attr-defined]
    os.lchflags(files["path"], stat.UF_NODUMP)  # type: ignore[attr-defined]
    os.lchflags(files["bound_file"], stat.UF_NODUMP)  # type: ignore[attr-defined]
    os.lchflags(files["bind_dest"], stat.UF_NODUMP)  # type: ignore[attr-defined]
    os.lchflags(files["bind_src"], stat.UF_NODUMP)  # type: ignore[attr-defined]


def test_os_chmod_and_lchmod(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import stat

    mode = os.stat(files["path"]).st_mode
    os.chmod(files["path"], mode | stat.S_IREAD | stat.S_IWRITE)
    os.chmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
    os.chmod(files["bind_dest"], mode | stat.S_IREAD | stat.S_IWRITE)
    os.chmod(files["bind_src"], mode | stat.S_IREAD | stat.S_IWRITE)

    if sys.platform != "win32" and sys.platform != "linux":
        os.lchmod(files["path"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bind_dest"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bind_src"], mode | stat.S_IREAD | stat.S_IWRITE)


def test_os_chmod_and_lchmod_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import stat

    mode = os.stat(files["bound_file"]).st_mode
    with pytest.raises(RulePermissionError):
        os.chmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)

    if sys.platform != "win32" and sys.platform != "linux":
        with pytest.raises(RulePermissionError):
            os.lchmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform == "win32", reason="requires no windows OS")
def test_os_chown_and_lchown(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    os.chown(files["path"], uid, gid)
    os.chown(files["bound_file"], uid, gid)
    os.chown(files["bind_dest"], uid, gid)
    os.chown(files["bind_src"], uid, gid)

    os.lchown(files["path"], uid, gid)
    os.lchown(files["bound_file"], uid, gid)
    os.lchown(files["bound_file"], uid, gid)
    os.lchown(files["bind_dest"], uid, gid)
    os.lchown(files["bind_src"], uid, gid)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no os.chown")
def test_os_chown_and_lchown_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    with pytest.raises(RulePermissionError):
        os.chown(files["bound_file"], uid, gid)

    with pytest.raises(RulePermissionError):
        os.lchown(files["bound_file"], uid, gid)


def test_os_replace(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io
    import os

    with io.open(files["to_replace"], "w") as f:
        f.write("To replace")
    os.replace(files["to_replace"], files["new_replace"])
    os.unlink(files["new_replace"])

    with io.open(files["bind_to_replace"], "w") as f:
        f.write("To replace")
    os.replace(files["bind_to_replace"], files["new_bind_replace"])
    os.unlink(files["new_bind_replace"])

    with pytest.raises(RuleFileNotFoundError):
        os.replace(files["ignore"], files["new_replace"])


def test_os_replace_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.replace(files["bound_file"], files["bound_file"])


def test_os_truncate(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io
    import os

    with io.open(files["to_truncate"], "w") as f:
        f.write("To truncate")
    os.truncate(files["to_truncate"], 3)
    assert os.path.getsize(files["to_truncate"]) == 3
    os.unlink(files["to_truncate"])

    with io.open(files["bind_to_truncate"], "w") as f:
        f.write("To truncate")
    os.truncate(files["bind_to_truncate"], 3)
    assert os.path.getsize(files["bind_to_truncate"]) == 3
    os.unlink(files["bind_to_truncate"])

    bf = files["bind_src"] / "bound_file.txt"
    os.truncate(bf, 3)
    assert os.path.getsize(bf) == 3
    bf.write_text("Content")


def test_os_truncate_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.truncate(files["bound_file"], 3)


def test_os_utime(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    now = time.time()
    yesterday = now - 86400

    import os

    os.utime(files["visible"], (yesterday, now))
    assert os.path.getatime(files["visible"]) == yesterday
    assert os.path.getmtime(files["visible"]) == now
    os.utime(files["bound_file"], (yesterday, now))
    assert os.path.getatime(files["bound_file"]) == yesterday
    assert os.path.getmtime(files["bound_file"]) == now

    os.utime(files["bind_src"], (yesterday, now))


def test_os_utime_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    now = time.time()
    yesterday = now - 86400

    with pytest.raises(RulePermissionError):
        os.utime(files["bound_file"], (yesterday, now))


def test_os_scandir(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with os.scandir(files["path"]) as entries:
        rc = list(entries)
    rc_name = [r.name for r in rc]
    assert "bind_src" in rc_name
    assert "bind_dest" in rc_name
    assert "visible.txt" in rc_name
    assert "ignore.log" not in rc_name
    assert rc[0].is_file() or rc[0].is_dir()

    with os.scandir(files["bind_dest"]) as entries:
        rc = list(entries)
    rc_name = [r.name for r in rc]
    assert "bound_file.txt" in rc_name

    with os.scandir(files["bind_src"]) as b:
        assert "bound_file.txt" in [e.name for e in b]


def test_os_scandir_entry_is_pathlike(files: Dict[str, Path]) -> None:  # noqa: F811
    """A scanned entry must be usable as a path, and expose the aliased path, not the real one."""
    rules = [
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with os.scandir(files["bind_dest"]) as entries:
        entry = next(e for e in entries if e.name == "bound_file.txt")

    assert isinstance(entry, os.PathLike)
    assert os.fspath(entry) == entry.path
    assert Path(entry) == files["bind_dest"] / "bound_file.txt"


def test_os_walk(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    rc = list(os.walk(files["path"]))
    assert rc[0][0] == str(files["path"])
    assert "bind_src" in rc[0][1]
    assert "bind_dest" in rc[0][1]
    rc_bind_dest = list(filter(lambda x: "bind_dest" in x[0], rc))
    assert rc_bind_dest
    assert "bound_file.txt" in rc_bind_dest[0][2]

    rc = list(os.walk(files["bind_dest"]))
    assert rc[0][0] == str(files["bind_dest"])
    assert "bound_file.txt" in rc[0][2]


def test_os_makedirs_and_removedirs(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    os.makedirs(files["path"] / "dir_to_remove" / "inner")
    os.removedirs(files["path"] / "dir_to_remove" / "inner")

    os.makedirs(files["bind_dest"] / "dir_to_remove" / "inner")
    os.removedirs(files["bind_dest"] / "dir_to_remove" / "inner")

    os.makedirs(files["bind_src"] / "dir_to_remove" / "inner")
    os.removedirs(files["bind_src"] / "dir_to_remove" / "inner")


def test_os_renames(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io
    import os

    with io.open(files["to_rename"], "w") as f:
        f.write("To rename")
    os.renames(files["to_rename"], files["new_rename"])
    os.unlink(files["new_rename"])


def test_os_walk_and_fwalk(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    root, dirs, dir_files = next(os.walk(files["path"], topdown=True))
    assert root == str(files["path"])
    assert "visible.txt" in dir_files
    assert "ignore.log" not in dir_files

    root, dirs, dir_files = next(os.walk(files["bind_dest"], topdown=True))
    assert root == str(files["bind_dest"])
    assert "bound_file.txt" in dir_files

    root, dirs, dir_files = next(os.walk(files["bind_src"], topdown=True))
    assert root == str(files["bind_src"])
    assert "bound_file.txt" in dir_files


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no posix module")
def test_os_and_posix_chroot_refused(files: Dict[str, Path]) -> None:  # noqa: F811
    """guard_files guards both os.chroot and posix.chroot the same
    way: a target outside the exposed rules is refused before the
    real chroot(2) call is ever attempted, on either door.
    """
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-ro={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import posix

    with pytest.raises(RuleFileNotFoundError):
        os.chroot(files["ignore"])

    with pytest.raises(RuleFileNotFoundError):
        posix.chroot(files["ignore"])
