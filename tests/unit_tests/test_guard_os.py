import io
import os
import pytest
import stat
import sys
import time

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
from test_guard_io import files


@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import _deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    _deactivate_guard_files()


def test_os_listdir_filters_ignored_files_and_bind(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)

    entries = os.listdir(files['path'])
    assert "ignore.log" not in entries
    assert "bind_src" not in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries

    entries = os.listdir(files['bind_dest'])
    assert "bound_file.txt" in entries

    entries = os.listdir(files['bind_src'])
    assert not entries


def test_os_scandir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)
    with os.scandir(files['path']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert "ignore.log" not in entries
    assert "visible.txt" in entries

    with os.scandir(files['bind_dest']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert "bound_file.txt" in entries

    with os.scandir(files['bind_src']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert not entries


def test_os_statand_stat_andlstat(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)
    assert os.stat(files['visible'])
    with pytest.raises(FileNotFoundError):
        assert os.stat(files['ignore'])
    assert os.stat(files["home_link"], follow_symlinks=True)
    assert os.stat(files['bound_file'], follow_symlinks=True)
    assert os.stat(files["bind_dest"], follow_symlinks=True)
    with pytest.raises(FileNotFoundError):
        assert os.stat(files["bind_src"], follow_symlinks=True)

    assert os.lstat(files['visible'])
    with pytest.raises(FileNotFoundError):
        assert os.lstat(files['ignore'])
    assert os.lstat(files["home_link"])
    assert os.lstat(files['bound_file'])
    assert os.lstat(files["bind_dest"])
    with pytest.raises(FileNotFoundError):
        assert os.lstat(files["bind_src"])


def test_os_link_symlink_and_readlink(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)

    assert os.readlink(files['home_link']) == str(files['visible'])
    assert os.readlink(files['home_link_to_bind_src']) == str(files["bound_file"])
    assert os.readlink(files['home_link_relative_to_bind_src']) == str(
        files["bound_file"])
    assert os.readlink(files['link_to_bind']) == str(files["bound_file"])
    assert os.readlink(
        files['link_relative_to_bind']) == str(files["bound_file"])
    with pytest.raises(FileNotFoundError):
        assert os.readlink(files['home_link_to_ignore'])

    os.link(files['visible'], files['new_link'])
    assert files['new_link'].exists()
    os.remove(files['new_link'])

    os.link(files['bound_file'], files['new_link_to_bind'])
    assert files['new_link_to_bind'].exists()
    os.unlink(files['new_link_to_bind'])

    with pytest.raises(FileNotFoundError):
        os.link(files['bind_src'] / "toto", files['new_link'])

    os.symlink(files['visible'], files['new_link'])
    assert files['new_link'].exists()
    assert os.readlink(files['new_link']) == str(
        files['visible'])
    os.remove(files['new_link'])

    os.symlink(files['visible'], files['new_link_to_bind'])
    assert files['new_link_to_bind'].exists()
    assert os.readlink(files['new_link_to_bind']) == str(
        files['visible'])
    os.unlink(files['new_link_to_bind'])

    with pytest.raises(FileNotFoundError):
        os.symlink(files['bind_src'], files['new_link'])


def test_os_remove(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    (files["path"] / "to_remove.txt").write_text("To remove")
    assert os.remove(files["path"] / "to_remove.txt") is None

    with pytest.raises(FileNotFoundError):
        assert os.remove(files['ignore'])
    with open(files["bind_dest"] / "to_remove.txt", "w") as f:
        f.write("To remove")
    assert os.remove(files["bind_dest"] / "to_remove.txt") is None


def test_os_mkdir_removedirs_and_rmdir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    os.mkdir(files["path"] / "dir_to_remove")
    assert os.rmdir(files["path"] / "dir_to_remove") is None

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    assert os.rmdir(files["bind_dest"] / "dir_to_remove") is None

    with pytest.raises(FileNotFoundError):
        os.mkdir(files["bind_src"] / "dir_to_remove")

    os.mkdir(files["path"] / "dir_to_remove")
    assert os.removedirs(files["path"] / "dir_to_remove") is None

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    assert os.removedirs(files["bind_dest"] / "dir_to_remove") is None

    with pytest.raises(FileNotFoundError):
        os.mkdir(files["bind_src"] / "dir_to_remove")


def test_os_rename(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(files["to_rename"], "w") as f:
        f.write("To rename")
    assert os.rename(files["to_rename"],
                     files["new_rename"]) is None
    os.unlink(files["new_rename"])

    with io.open(files["bind_to_rename"], "w") as f:
        f.write("To rename")
    assert os.rename(files["bind_to_rename"],
                     files["new_bind_rename"]) is None
    os.unlink(files["new_bind_rename"])

    with pytest.raises(FileNotFoundError):
        assert os.rename(files["bind_src"] / "toto", files["visible"])


def test_os_chdir_and_getcwd(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    old_dir = os.getcwd()
    os.chdir(files["path"])
    assert str(files["path"]) == os.getcwd()
    os.chdir(files["bind_dest"])
    assert str(files["bind_dest"]) == os.getcwd()
    with pytest.raises(FileNotFoundError):
        os.chdir(files["bind_src"])
    os.chdir(old_dir)


def test_os_access(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.access(files["path"], os.R_OK)
    assert os.access(files["visible"], os.R_OK)
    assert os.access(files["bound_file"], os.R_OK)
    assert os.access(files["bind_dest"], os.R_OK)
    with pytest.raises(FileNotFoundError):
        assert os.access(files["bind_src"], os.R_OK)


@pytest.mark.skipif(not (sys.platform != "win32" and sys.platform != "linux"),
                    reason="requires special os")
def test_os_chflags_and_lchflags(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.chflags(files["path"], stat.SF_ARCHIVED)
    assert os.chflags(files["bound_file"], stat.SF_ARCHIVED)
    assert os.lchflags(files["path"], stat.SF_ARCHIVED)
    assert os.lchflags(files["bound_file"], stat.SF_ARCHIVED)
    assert os.lchflags(files["bind_dest"], stat.SF_ARCHIVED)
    with pytest.raises(FileNotFoundError):
        assert os.lchflags(files["bind_src"], stat.SF_ARCHIVED)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid(),
                    reason="requires no windows OS")
def test_os_chroot(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.chroot(files["path"])


def test_os_chmod_and_lchmod(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    mode = os.stat(files["path"]).st_mode
    assert os.chmod(files["path"], mode | stat.S_IREAD) is None
    assert os.chmod(files["bound_file"],
                    mode | stat.S_IREAD) is None
    assert os.chmod(files["bind_dest"],
                    mode | stat.S_IREAD) is None
    with pytest.raises(FileNotFoundError):
        os.chmod(files["bind_src"],mode | stat.S_IREAD)

    if sys.platform != "win32" and sys.platform != "linux":
        assert os.lchmod(files["path"], mode | stat.S_IREAD) is None
        assert os.lchmod(files["bound_file"],
                         mode | stat.S_IREAD) is None
        assert os.lchmod(files["bound_file"],
                        mode | stat.S_IREAD) is None
        assert os.lchmod(files["bind_dest"],
                        mode | stat.S_IREAD) is None
        with pytest.raises(FileNotFoundError):
            os.lchmod(files["bind_src"],mode | stat.S_IREAD)


# @pytest.mark.skipif(sys.platform != "win32",
#                     reason="requires no windows OS")
def test_os_chown_and_lchown(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    assert os.chown(files["path"], uid, gid) is None
    assert os.chown(files["bound_file"],
                    uid, gid) is None
    assert os.chown(files["bind_dest"],
                    uid, gid) is None
    with pytest.raises(FileNotFoundError):
        os.chown(files["bind_src"],
                    uid, gid)

    assert os.lchown(files["path"], uid, gid) is None
    assert os.lchown(files["bound_file"],
                     uid, gid) is None
    assert os.lchown(files["bound_file"],
                    uid, gid) is None
    assert os.lchown(files["bind_dest"],
                    uid, gid) is None
    with pytest.raises(FileNotFoundError):
        os.lchown(files["bind_src"],
                    uid, gid)


def test_os_replace(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(files["to_replace"], "w") as f:
        f.write("To replace")
    os.replace(files["to_replace"],
               files["new_replace"])
    os.unlink(files["new_replace"])

    with io.open(files["bind_to_replace"], "w") as f:
        f.write("To replace")
    os.replace(files["bind_to_replace"],
               files["new_bind_replace"])
    os.unlink(files["new_bind_replace"])

    with pytest.raises(FileNotFoundError):
        os.replace(files["ignore"],files["new_replace"])
    with pytest.raises(FileNotFoundError):
        os.replace(files["bind_src"],files["new_replace"])


def test_os_truncate(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

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

    with pytest.raises(FileNotFoundError):
        os.truncate(files["bind_src"], 3)


def test_os_utime(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    now = time.time()
    yesterday = now - 86400

    os.utime(files["visible"], (yesterday, now))
    assert os.path.getatime(files["visible"]) == yesterday
    assert os.path.getmtime(files["visible"]) == now
    os.utime(files["bound_file"], (yesterday, now))
    assert os.path.getatime(files["bound_file"]) == yesterday
    assert os.path.getmtime(files["bound_file"]) == now

    with pytest.raises(FileNotFoundError):
        os.utime(files["bind_src"], (yesterday, now))


def test_os_scandir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with os.scandir(files["path"]) as entries:
        rc = list(entries)
    assert not next(filter(lambda x: x.path == str(files["bind_src"]), rc), None)
    assert next(filter(lambda x: x.path == str(files["bind_dest"]), rc), None)
    assert next(filter(lambda x: x.path == str(files["visible"]), rc), None)
    assert not next(filter(lambda x: x.path == str(files["ignore"]), rc), None)

    with os.scandir(files["bind_dest"]) as entries:
        rc = list(entries)
    assert next(filter(lambda x: x.path == str(files["bound_file"]), rc), None)

    with os.scandir(files["bind_src"]) as entries:
        rc = list(entries)
    assert not rc


def test_os_walk(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    rc = list(os.walk(files["path"]))
    assert rc[0][0] == str(files["path"])
    assert "bind_src" not in rc[0][1]
    assert "bind_dest" in rc[0][1]
    assert rc[1][0] == str(files["bind_dest"])
    assert "bound_file.txt" in rc[1][2]

    rc = list(os.walk(files["bind_dest"]))
    assert rc[0][0] == str(files["bind_dest"])
    assert "bound_file.txt" in rc[0][2]
