from pathlib import Path

import pytest

from pysandboxes.sb_types import ConfigLine
from .test_guard_io import files, activate_guard_files_rules, _reset_rules


@pytest.mark.skip(reason="not implemented")
def test_shutil_chown(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import shutil
    uid = os.stat(files["bind_dest"]).st_uid
    gid = os.stat(files["bind_dest"]).st_gid

    shutil.chown(files["bind_dest"], uid, gid)


def test_shutil_copy(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.copy(files["visible"], files["new_replace"]) is None
    files["new_replace"].unlink()
    shutil.copy(files["bound_file"], files["new_replace"]) is None
    files["new_replace"].unlink()


def test_shutil_copy2(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    import pathlib
    shutil.copy2(files["visible"], files["new_replace"]) is None
    files["new_replace"].unlink()
    shutil.copy2(files["bound_file"], files["new_replace"]) is None
    files["new_replace"].unlink()
    out=files["bind_dest"] / "copy.txt"
    assert shutil.copy2(files["bound_file"], out) is out
    pathlib.Path(out).unlink()

def test_shutil_copyfile(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.copyfile(files["visible"], files["new_rename"])
    assert files["new_rename"].exists()
    files["new_rename"].unlink()

    import pathlib
    shutil.copyfile(files["bound_file"], files["bind_to_replace"])
    assert pathlib.Path(files["bind_to_replace"]).exists()
    pathlib.Path(files["bind_to_replace"]).unlink()


def test_shutil_copymode(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.copymode(files["visible"], files["bound_file"])
    shutil.copymode(files["bound_file"], files["bound_file"])


def test_shutil_copystat(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.copystat(files["visible"], files["bound_file"]) is None
    shutil.copystat(files["bound_file"], files["visible"]) is None


def test_shutil_copytree_and_move(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    if (files["path"] / "tmp").exists():
        (files["path"] / "tmp").rmdir()
    shutil.copytree(files["bind_dest"], files["path"] / "tmp") is None
    shutil.move(files["path"] / "tmp", files["path"] / "tmp2") is None
    shutil.rmtree(files["path"] / "tmp2")


def test_shutil_disk_usage(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.disk_usage(files["bind_dest"]) is None


def test_shutil_make_archive(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    shutil.make_archive(
        base_name=files["path"] / "arch",
        format="zip",
        root_dir=files["bind_dest"]  # dossier à compresser
    )

def test_shutil_rmtree(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    import os
    d = files["path"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    shutil.rmtree(d,ignore_errors=False, onerror=None, onexc=None, dir_fd=None)

    import os
    d = files["bind_dest"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    shutil.rmtree(d,ignore_errors=False, onerror=None, onexc=None, dir_fd=None)


def test_shutil_move(files):
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil
    import os
    s = files["path"] / "dir_to_move"
    d = files["path"] / "dir_moved"
    s.mkdir()
    (s / "inner").mkdir()
    shutil.move(s,d,copy_function=shutil.copy2)
