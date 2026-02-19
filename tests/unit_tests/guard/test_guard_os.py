import stat
import sys
import time
from pathlib import Path
from typing import Dict

import pytest

from pysandboxes import RuleFileNotFoundError, RulePermissionError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules, files


def test_os_listdir_filters_ignored_files_and_bind(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    entries = os.listdir(files["path"])
    assert "ignore.log" not in entries
    assert "bind_src" not in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries

    entries = os.listdir(files["bind_dest"])
    assert "bound_file.txt" in entries

    with pytest.raises(RuleFileNotFoundError):
        os.listdir(files["bind_src"])


def test_os_statand_stat_and_lstat(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.stat(files["visible"])
    with pytest.raises(RuleFileNotFoundError):
        assert os.stat(files["ignore"])
    assert os.stat(files["home_link"], follow_symlinks=True)
    assert os.stat(files["bound_file"], follow_symlinks=True)
    assert os.stat(files["bind_dest"], follow_symlinks=True)
    with pytest.raises(RuleFileNotFoundError):
        assert os.stat(files["bind_src"], follow_symlinks=True)

    assert os.lstat(files["visible"])
    with pytest.raises(RuleFileNotFoundError):
        assert os.lstat(files["ignore"])
    assert os.lstat(files["home_link"])
    assert os.lstat(files["bound_file"])
    assert os.lstat(files["bind_dest"])

    with pytest.raises(RuleFileNotFoundError):
        assert os.lstat(files["bind_src"])


def test_os_listxattr(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.listxattr(files["visible"]) == []

    with pytest.raises(RuleFileNotFoundError):
        os.listxattr(files["ignore"])

    with pytest.raises(RuleFileNotFoundError):
        os.listxattr(files["bind_src"])


def test_os_xattr(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(RuleFileNotFoundError):
        os.getxattr(files["bind_src"], "user.comment")


def test_os_link_symlink_and_readlink(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.readlink(files["home_link"]) == str(files["visible"])
    assert os.readlink(files["home_link_to_bind_src"]) == str(files["bound_file"])
    assert os.readlink(files["home_link_relative_to_bind_src"]) == str(
        files["bound_file"]
    )
    assert os.readlink(files["link_to_bind"]) == str(files["bound_file"])
    assert os.readlink(files["link_relative_to_bind"]) == str(files["bound_file"])
    with pytest.raises(RuleFileNotFoundError):
        assert os.readlink(files["home_link_to_ignore"])

    files["new_link"].unlink(missing_ok=True)
    os.link(files["visible"], files["new_link"])
    assert files["new_link"].exists()
    os.remove(files["new_link"])

    files["new_link_to_bind"].unlink(missing_ok=True)
    os.link(files["bound_file"], files["new_link_to_bind"])
    assert os.path.exists(files["new_link_to_bind"])
    os.unlink(files["new_link_to_bind"])

    with pytest.raises(RuleFileNotFoundError):
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

    with pytest.raises(RuleFileNotFoundError):
        os.symlink(files["new_link"], files["bind_src"] / "link")

    files["new_link"].unlink(missing_ok=True)
    os.symlink(files["bind_dest"], files["new_link"])
    assert os.path.exists(files["new_link"])


def test_os_remove(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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



def test_os_remove_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.remove(files["bound_file"])


def test_os_mkdir_removedirs_and_rmdir(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(RuleFileNotFoundError):
        os.mkdir(files["bind_src"] / "dir_to_remove")

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

    with pytest.raises(RuleFileNotFoundError):
        os.mkdir(files["bind_src"] / "dir_to_remove")


def test_os_mkdir_removedirs_and_rmdir_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    os.rmdir(files["bind_dest"] / "dir_to_remove")

    with pytest.raises(RuleFileNotFoundError):
        os.mkdir(files["bind_src"] / "dir_to_remove")


def test_os_rename(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(RuleFileNotFoundError):
        os.rename(files["bind_src"] / "toto", files["visible"])

    with pytest.raises(RuleFileNotFoundError):
        os.rename(files["ignore"], str(files["ignore"]) + "-back")


def test_os_rename_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.rename(files["to_rename"], files["bound_file"])


def test_os_chdir_and_getcwd(files: Dict[str, Path]) -> None:
    import os

    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={os.environ['PWD']},{os.environ['PWD']}", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    old_dir = os.getcwd()
    os.chdir(files["path"])
    assert str(files["path"]) == os.getcwd()
    os.chdir(files["bind_dest"])
    assert str(files["bind_dest"]) == os.getcwd()
    with pytest.raises(RuleFileNotFoundError):
        os.chdir(files["bind_src"])
    os.chdir(old_dir)


def test_os_getcwdb(files: Dict[str, Path]) -> None:
    import os

    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={os.environ['PWD']},{os.environ['PWD']}", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    cwd = os.getcwdb()
    assert isinstance(cwd, bytes)
    assert cwd.decode(sys.getfilesystemencoding()) == os.getcwd()


def test_os_open_readonly(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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


def test_os_open_writeonly(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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


def test_os_open_writeonly_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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


def test_os_open_readwrite(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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


def test_os_open_readwrite_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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


def test_os_access_read_write(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.access(files["path"], os.R_OK | os.W_OK)
    assert os.access(files["visible"], os.R_OK | os.W_OK)
    assert os.access(files["bound_file"], os.R_OK | os.W_OK)
    assert os.access(files["bind_dest"], os.R_OK | os.W_OK)
    assert not os.access(files["bind_src"], os.R_OK | os.W_OK)


def test_os_access_read_only(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.access(files["path"], os.R_OK | os.W_OK)
    assert os.access(files["visible"], os.R_OK | os.W_OK)
    assert os.access(files["bound_file"], os.R_OK | os.W_OK)
    assert os.access(files["bind_dest"], os.R_OK | os.W_OK)
    assert not os.access(files["bind_src"], os.R_OK | os.W_OK)


@pytest.mark.skipif(
    not (sys.platform != "win32" and sys.platform != "linux"),
    reason="requires special os",
)
def test_os_chflags_and_lchflags(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    assert os.chflags(files["path"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]
    assert os.chflags(files["bound_file"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]
    assert os.lchflags(files["path"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]
    assert os.lchflags(files["bound_file"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]
    assert os.lchflags(files["bind_dest"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]
    with pytest.raises(RuleFileNotFoundError):
        assert os.lchflags(files["bind_src"], stat.SF_ARCHIVED)  # type: ignore[attr-defined]


def test_os_chmod_and_lchmod(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import stat

    mode = os.stat(files["path"]).st_mode
    os.chmod(files["path"], mode | stat.S_IREAD | stat.S_IWRITE)
    os.chmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
    os.chmod(files["bind_dest"], mode | stat.S_IREAD | stat.S_IWRITE)
    with pytest.raises(RuleFileNotFoundError):
        os.chmod(files["bind_src"], mode | stat.S_IREAD | stat.S_IWRITE)

    if sys.platform != "win32" and sys.platform != "linux":
        os.lchmod(files["path"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bound_file"], mode | stat.S_IREAD | stat.S_IWRITE)
        os.lchmod(files["bind_dest"], mode | stat.S_IREAD | stat.S_IWRITE)
        with pytest.raises(RuleFileNotFoundError):
            os.lchmod(files["bind_src"], mode | stat.S_IREAD | stat.S_IWRITE)


def test_os_chmod_and_lchmod_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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
def test_os_chown_and_lchown(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    os.chown(files["path"], uid, gid)
    os.chown(files["bound_file"], uid, gid)
    os.chown(files["bind_dest"], uid, gid)
    with pytest.raises(RuleFileNotFoundError):
        os.chown(files["bind_src"], uid, gid)

    os.lchown(files["path"], uid, gid)
    os.lchown(files["bound_file"], uid, gid)
    os.lchown(files["bound_file"], uid, gid)
    os.lchown(files["bind_dest"], uid, gid)
    with pytest.raises(RuleFileNotFoundError):
        os.lchown(files["bind_src"], uid, gid)


def test_os_chown_and_lchown_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    with pytest.raises(RulePermissionError):
        os.chown(files["bound_file"], uid, gid)

    with pytest.raises(RulePermissionError):
        os.lchown(files["bound_file"], uid, gid)


def test_os_replace(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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
    with pytest.raises(RuleFileNotFoundError):
        os.replace(files["bind_src"], files["new_replace"])


def test_os_replace_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.replace(files["bound_file"], files["bound_file"])


def test_os_truncate(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(RuleFileNotFoundError):
        os.truncate(files["bind_src"], 3)


def test_os_truncate_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with pytest.raises(RulePermissionError):
        os.truncate(files["bound_file"], 3)


def test_os_utime(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(RuleFileNotFoundError):
        os.utime(files["bind_src"], (yesterday, now))


def test_os_utime_refused(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    now = time.time()
    yesterday = now - 86400

    with pytest.raises(RulePermissionError):
        os.utime(files["bound_file"], (yesterday, now))


def test_os_scandir(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    with os.scandir(files["path"]) as entries:
        rc = list(entries)
    rc_name = [r.name for r in rc]
    assert "bind_src" not in rc_name
    assert "bind_dest" in rc_name
    assert "visible.txt" in rc_name
    assert "ignore.log" not in rc_name
    assert rc[0].is_file() or rc[0].is_dir()

    with os.scandir(files["bind_dest"]) as entries:
        rc = list(entries)
    rc_name = [r.name for r in rc]
    assert "bound_file.txt" in rc_name

    with pytest.raises(RuleFileNotFoundError):
        with os.scandir(files["bind_src"]):
            pass


def test_os_walk(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    rc = list(os.walk(files["path"]))
    assert rc[0][0] == str(files["path"])
    assert "bind_src" not in rc[0][1]
    assert "bind_dest" in rc[0][1]
    rc_bind_dest = list(filter(lambda x: "bind_dest" in x[0], rc))
    assert rc_bind_dest
    assert "bound_file.txt" in rc_bind_dest[0][2]

    rc = list(os.walk(files["bind_dest"]))
    assert rc[0][0] == str(files["bind_dest"])
    assert "bound_file.txt" in rc[0][2]


def test_os_makedirs_and_removedirs(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os

    os.makedirs(files["path"] / "dir_to_remove" / "inner")
    os.removedirs(files["path"] / "dir_to_remove" / "inner")

    os.makedirs(files["bind_dest"] / "dir_to_remove" / "inner")
    os.removedirs(files["bind_dest"] / "dir_to_remove" / "inner")

    with pytest.raises(RuleFileNotFoundError):
        os.makedirs(files["bind_src"] / "dir_to_remove" / "inner")

    with pytest.raises(RuleFileNotFoundError):
        os.removedirs(files["bind_src"] / "dir_to_remove" / "inner")


def test_os_renames(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io
    import os

    with io.open(files["to_rename"], "w") as f:
        f.write("To rename")
    os.renames(files["to_rename"], files["new_rename"])
    os.unlink(files["new_rename"])


def test_os_walk_and_fwalk(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
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

    with pytest.raises(StopIteration):
        next(os.walk(files["bind_src"], topdown=True))


# Missing tests
# - os.chroot
