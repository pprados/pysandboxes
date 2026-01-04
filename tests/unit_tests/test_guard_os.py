import time

import io
import os
import pytest
import stat
import sys

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
from test_guard_io import files

@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    deactivate_guard_files()

def test_os_listdir_filters_ignored_files(files):
    rules = [f"--ignore=*.log"]
    activate_guard_files(rules)
    entries = os.listdir(files['ignore'].parent)
    assert "ignore.log" not in entries


def test_os_listdir_filters_ignored_files_and_bind(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)
    entries = os.listdir(files['bind_dest'])
    assert "bound_file.txt" in entries
    entries = os.listdir(files['path'])
    assert "ignore.log" not in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries


def test_os_listdir(files):
    rules = [
        f"--bind={files['bind_src']},/data",
        f"--bind={files['bind_src']},/",
    ]
    activate_guard_files(rules)
    # Access using the dest path should redirect to src
    with io.open("/bound_file.txt") as f:
        content = f.read()
    with io.open("/data/bound_file.txt") as f:
        content = f.read()
    assert content == "Content"
    entries = os.listdir("/")
    assert "bound_file.txt" in entries


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


def test_os_statand_lstat(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)
    import os
    assert os.stat(files['visible'])
    with pytest.raises(FileNotFoundError):
        assert os.stat(files['ignore'])
    assert os.stat(files["home_link"], follow_symlinks=True)
    assert os.stat(files['bind_dest'] / 'bound_file.txt', follow_symlinks=True)

    assert os.lstat(files["home_link"])
    assert os.lstat(files['bind_dest'] / 'bound_file.txt')


def test_os_link_symlink_and_readlink(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}"
    ]
    activate_guard_files(rules)

    import os
    bound_file = str(files['bind_dest'] / 'bound_file.txt')
    assert os.readlink(files['home_link']) == str(files['visible'])
    assert os.readlink(files['home_link_to_bind_src']) == bound_file
    assert os.readlink(files['home_link_relative_to_bind_src']) == bound_file
    assert os.readlink(files['bind_dest'] / 'link_to_bind_src') == bound_file
    assert os.readlink(
        files['bind_dest'] / 'link_relative_to_bind_src') == bound_file
    with pytest.raises(FileNotFoundError):
        assert os.readlink(files['home_link_to_ignore'])

    os.link(files['path'] / "visible.txt", files['path'] / "new_link.txt")
    os.remove(files['path'] / "new_link.txt")

    os.link(files['path'] / "visible.txt", files['bind_src'] / "new_link.txt")
    os.unlink(files['bind_src'] / "new_link.txt")

    os.symlink(files['path'] / "visible.txt", files['path'] / "new_symlink.txt")
    assert os.readlink(files['path'] / "new_symlink.txt") == str(
        files['visible'])
    os.remove(files['path'] / "new_symlink.txt")

    os.symlink(files['path'] / "visible.txt", files['bind_src'] / "new_symlink.txt",
               )
    assert os.readlink(files['bind_src'] / "new_symlink.txt") == str(
        files['visible'])
    os.unlink(files['bind_src'] / "new_symlink.txt")


def test_os_remove(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    (files["path"] / "to_remove.txt").write_text("To remove")
    assert os.remove(files["path"] / "to_remove.txt") is None

    with pytest.raises(FileNotFoundError):
        assert os.remove(files['ignore'])
    with open(files["bind_dest"] / "to_remove.txt", "w") as f:
        f.write("To remove")
    assert os.remove(files["bind_dest"] / "to_remove.txt") is None


def test_os_removedirs_and_rmdir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    os.mkdir(files["path"] / "dir_to_remove")
    assert os.rmdir(files["path"] / "dir_to_remove") is None

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    assert os.rmdir(files["bind_dest"] / "dir_to_remove") is None

    os.mkdir(files["path"] / "dir_to_remove")
    assert os.removedirs(files["path"] / "dir_to_remove") is None

    os.mkdir(files["bind_dest"] / "dir_to_remove")
    assert os.removedirs(files["bind_dest"] / "dir_to_remove") is None


def test_os_rename(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    with io.open(files["path"] / "to_rename.txt", "w") as f:
        f.write("To rename")
    assert os.rename(files["path"] / "to_rename.txt",
                     files["path"] / "new_rename.txt") is None

    with io.open(files["bind_dest"] / "to_rename.txt", "w") as f:
        f.write("To rename")
    assert os.rename(files["bind_dest"] / "to_rename.txt",
                     files["bind_dest"] / "new_rename.txt") is None


def test_os_chdir_and_getcwd(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    old_dir = os.getcwd()
    os.chdir(files["path"])
    assert str(files["path"]) == os.getcwd()
    os.chdir(files["bind_dest"])
    assert str(files["bind_dest"]) == os.getcwd()
    os.chdir(old_dir)


def test_os_access(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.access(files["path"], os.R_OK)
    assert os.access(files["bind_dest"] / "bound_file.txt", os.R_OK)


@pytest.mark.skipif(not (sys.platform != "win32" and sys.platform != "linux"),
                    reason="requires special os")
def test_os_chflags_and_lchflags(files):

    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.chflags(files["path"], stat.SF_ARCHIVED)
    assert os.chflags(files["bind_dest"] / "bound_file.txt", stat.SF_ARCHIVED)
    assert os.lchflags(files["path"], stat.SF_ARCHIVED)
    assert os.lchflags(files["bind_dest"] / "bound_file.txt", stat.SF_ARCHIVED)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid(),
                    reason="requires no windows OS")
def test_os_chroot(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.chroot(files["path"])
    assert os.chroot("bound_file.txt")


def test_os_chmod_and_lchmod(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    mode = os.stat(files["path"]).st_mode
    assert os.chmod(files["path"], mode | stat.S_IREAD) is None
    assert os.chmod(files["bind_dest"] / "bound_file.txt",
                    mode | stat.S_IREAD) is None
    if sys.platform != "win32" and sys.platform != "linux":
        assert os.lchmod(files["path"], mode | stat.S_IREAD) is None
        assert os.lchmod(files["bind_dest"] / "bound_file.txt",
                         mode | stat.S_IREAD) is None


# @pytest.mark.skipif(sys.platform != "win32",
#                     reason="requires no windows OS")
def test_os_chown_and_lchown(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    uid = os.stat(files["path"]).st_uid
    gid = os.stat(files["path"]).st_gid
    assert os.chown(files["path"], uid, gid) is None
    assert os.chown(files["bind_dest"] / "bound_file.txt",
                    uid, gid) is None
    assert os.lchown(files["path"], uid, gid) is None
    assert os.lchown(files["bind_dest"] / "bound_file.txt",
                     uid, gid) is None


def test_os_replace(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(files["path"] / "to_replace.txt", "w") as f:
        f.write("To replace")
    os.replace(files["path"] / "to_replace.txt",
               files["path"] / "replaced.txt")

    with io.open(files["bind_dest"] / "to_replace.txt", "w") as f:
        f.write("To replace")
    os.replace(files["bind_dest"] / "to_replace.txt",
               files["bind_dest"] / "replaced.txt")

def test_os_truncate(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(files["path"] / "to_truncate.txt", "w") as f:
        f.write("To truncate")
    os.truncate(files["path"] / "to_truncate.txt", 3)

    with io.open(files["bind_dest"] / "to_truncate.txt", "w") as f:
        f.write("To truncate")
    os.truncate(files["bind_dest"] / "to_truncate.txt", 3)

def test_os_utime(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    now = time.time()
    yesterday = now - 86400


    os.utime(files["path"] / "visible.txt", (yesterday, now))
    os.utime(files["bind_dest"] / "bound_file.txt", (yesterday, now))