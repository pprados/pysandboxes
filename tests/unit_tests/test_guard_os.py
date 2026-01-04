import time

import io
import os
import pytest
import stat
import sys

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
from test_guard_io import temp_files

@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    deactivate_guard_files()

def test_os_listdir_filters_ignored_files(temp_files):
    rules = [f"--ignore=*.log"]
    activate_guard_files(rules)
    entries = os.listdir(temp_files['ignore'].parent)
    assert "ignore.log" not in entries


def test_os_listdir_filters_ignored_files_and_bind(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}"
    ]
    activate_guard_files(rules)
    entries = os.listdir(temp_files['bind_dest'])
    assert "bound_file.txt" in entries
    entries = os.listdir(temp_files['path'])
    assert "ignore.log" not in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries


def test_os_listdir(temp_files):
    rules = [
        f"--bind={temp_files['bind_src']},/data",
        f"--bind={temp_files['bind_src']},/",
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


def test_os_scandir(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}"
    ]
    activate_guard_files(rules)
    with os.scandir(temp_files['path']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert "ignore.log" not in entries
    assert "visible.txt" in entries

    with os.scandir(temp_files['bind_dest']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert "bound_file.txt" in entries


def test_os_statand_lstat(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}"
    ]
    activate_guard_files(rules)
    import os
    assert os.stat(temp_files['visible'])
    with pytest.raises(FileNotFoundError):
        assert os.stat(temp_files['ignore'])
    assert os.stat(temp_files["home_link"], follow_symlinks=True)
    assert os.stat(temp_files['bind_dest'] / 'bound_file.txt', follow_symlinks=True)

    assert os.lstat(temp_files["home_link"])
    assert os.lstat(temp_files['bind_dest'] / 'bound_file.txt')


def test_os_link_symlink_and_readlink(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}"
    ]
    activate_guard_files(rules)

    import os
    bound_file = str(temp_files['bind_dest'] / 'bound_file.txt')
    assert os.readlink(temp_files['home_link']) == str(temp_files['visible'])
    assert os.readlink(temp_files['home_link_to_bind_src']) == bound_file
    assert os.readlink(temp_files['home_link_relative_to_bind_src']) == bound_file
    assert os.readlink(temp_files['bind_dest'] / 'link_to_bind_src') == bound_file
    assert os.readlink(
        temp_files['bind_dest'] / 'link_relative_to_bind_src') == bound_file
    with pytest.raises(FileNotFoundError):
        assert os.readlink(temp_files['home_link_to_ignore'])

    os.link(temp_files['path'] / "visible.txt", temp_files['path'] / "new_link.txt")
    os.remove(temp_files['path'] / "new_link.txt")

    os.link(temp_files['path'] / "visible.txt", temp_files['bind_src'] / "new_link.txt")
    os.unlink(temp_files['bind_src'] / "new_link.txt")

    os.symlink(temp_files['path'] / "visible.txt", temp_files['path'] / "new_symlink.txt")
    assert os.readlink(temp_files['path'] / "new_symlink.txt") == str(
        temp_files['visible'])
    os.remove(temp_files['path'] / "new_symlink.txt")

    os.symlink(temp_files['path'] / "visible.txt", temp_files['bind_src'] / "new_symlink.txt",
               )
    assert os.readlink(temp_files['bind_src'] / "new_symlink.txt") == str(
        temp_files['visible'])
    os.unlink(temp_files['bind_src'] / "new_symlink.txt")


def test_os_remove(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    (temp_files["path"] / "to_remove.txt").write_text("To remove")
    assert os.remove(temp_files["path"] / "to_remove.txt") is None

    with pytest.raises(FileNotFoundError):
        assert os.remove(temp_files['ignore'])
    with open(temp_files["bind_dest"] / "to_remove.txt", "w") as f:
        f.write("To remove")
    assert os.remove(temp_files["bind_dest"] / "to_remove.txt") is None


def test_os_removedirs_and_rmdir(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    os.mkdir(temp_files["path"] / "dir_to_remove")
    assert os.rmdir(temp_files["path"] / "dir_to_remove") is None

    os.mkdir(temp_files["bind_dest"] / "dir_to_remove")
    assert os.rmdir(temp_files["bind_dest"] / "dir_to_remove") is None

    os.mkdir(temp_files["path"] / "dir_to_remove")
    assert os.removedirs(temp_files["path"] / "dir_to_remove") is None

    os.mkdir(temp_files["bind_dest"] / "dir_to_remove")
    assert os.removedirs(temp_files["bind_dest"] / "dir_to_remove") is None


def test_os_rename(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    with io.open(temp_files["path"] / "to_rename.txt", "w") as f:
        f.write("To rename")
    assert os.rename(temp_files["path"] / "to_rename.txt",
                     temp_files["path"] / "new_rename.txt") is None

    with io.open(temp_files["bind_dest"] / "to_rename.txt", "w") as f:
        f.write("To rename")
    assert os.rename(temp_files["bind_dest"] / "to_rename.txt",
                     temp_files["bind_dest"] / "new_rename.txt") is None


def test_os_chdir_and_getcwd(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os

    old_dir = os.getcwd()
    os.chdir(temp_files["path"])
    assert str(temp_files["path"]) == os.getcwd()
    os.chdir(temp_files["bind_dest"])
    assert str(temp_files["bind_dest"]) == os.getcwd()
    os.chdir(old_dir)


def test_os_access(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.access(temp_files["path"], os.R_OK)
    assert os.access(temp_files["bind_dest"] / "bound_file.txt", os.R_OK)


@pytest.mark.skipif(not (sys.platform != "win32" and sys.platform != "linux"),
                    reason="requires special os")
def test_os_chflags_and_lchflags(temp_files):

    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.chflags(temp_files["path"], stat.SF_ARCHIVED)
    assert os.chflags(temp_files["bind_dest"] / "bound_file.txt", stat.SF_ARCHIVED)
    assert os.lchflags(temp_files["path"], stat.SF_ARCHIVED)
    assert os.lchflags(temp_files["bind_dest"] / "bound_file.txt", stat.SF_ARCHIVED)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid(),
                    reason="requires no windows OS")
def test_os_chroot(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    assert os.chroot(temp_files["path"])
    assert os.chroot("bound_file.txt")


def test_os_chmod_and_lchmod(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    mode = os.stat(temp_files["path"]).st_mode
    assert os.chmod(temp_files["path"], mode | stat.S_IREAD) is None
    assert os.chmod(temp_files["bind_dest"] / "bound_file.txt",
                    mode | stat.S_IREAD) is None
    if sys.platform != "win32" and sys.platform != "linux":
        assert os.lchmod(temp_files["path"], mode | stat.S_IREAD) is None
        assert os.lchmod(temp_files["bind_dest"] / "bound_file.txt",
                         mode | stat.S_IREAD) is None


# @pytest.mark.skipif(sys.platform != "win32",
#                     reason="requires no windows OS")
def test_os_chown_and_lchown(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    import os
    uid = os.stat(temp_files["path"]).st_uid
    gid = os.stat(temp_files["path"]).st_gid
    assert os.chown(temp_files["path"], uid, gid) is None
    assert os.chown(temp_files["bind_dest"] / "bound_file.txt",
                    uid, gid) is None
    assert os.lchown(temp_files["path"], uid, gid) is None
    assert os.lchown(temp_files["bind_dest"] / "bound_file.txt",
                     uid, gid) is None


def test_os_replace(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(temp_files["path"] / "to_replace.txt", "w") as f:
        f.write("To replace")
    os.replace(temp_files["path"] / "to_replace.txt",
               temp_files["path"] / "replaced.txt")

    with io.open(temp_files["bind_dest"] / "to_replace.txt", "w") as f:
        f.write("To replace")
    os.replace(temp_files["bind_dest"] / "to_replace.txt",
               temp_files["bind_dest"] / "replaced.txt")

def test_os_truncate(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    with io.open(temp_files["path"] / "to_truncate.txt", "w") as f:
        f.write("To truncate")
    os.truncate(temp_files["path"] / "to_truncate.txt",3)

    with io.open(temp_files["bind_dest"] / "to_truncate.txt", "w") as f:
        f.write("To truncate")
    os.truncate(temp_files["bind_dest"] / "to_truncate.txt",3)

def test_os_utime(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    now = time.time()
    yesterday = now - 86400


    os.utime(temp_files["path"] / "visible.txt",(yesterday,now))
    os.utime(temp_files["bind_dest"] / "bound_file.txt",(yesterday,now))