import os

import pytest
import shutil

from pysandboxes.guard_files import activate_guard_files
from .test_guard_io import files, str_activate_guard_files


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_files import _deactivate_guard_files

    yield
    _deactivate_guard_files()


@pytest.mark.skip(reason="not implemented")
def test_shutil_chown(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    uid = os.stat(files["bind_dest"]).st_uid
    gid = os.stat(files["bind_dest"]).st_gid

    shutil.chown(files["bind_dest"],uid,gid)

def test_shutil_copy(files):  # TODO: write
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copy(files["visible"], files["new_replace"]) is None
    files["new_replace"].unlink()
    shutil.copy(files["bound_file"], files["new_replace"]) is None
    files["new_replace"].unlink()

def test_shutil_copy2(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copy2(files["visible"], files["new_replace"]) is None
    files["new_replace"].unlink()
    shutil.copy2(files["bound_file"], files["new_replace"]) is None
    files["new_replace"].unlink()

def test_shutil_copyfile(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copyfile(files["visible"], files["new_rename"])
    assert files["new_rename"].exists()
    files["new_rename"].unlink()

    shutil.copyfile(files["bound_file"], files["bind_to_replace"])
    assert files["bind_to_replace"].exists()
    files["bind_to_replace"].unlink()

def test_shutil_copymode(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copymode(files["visible"], files["bound_file"])
    shutil.copymode(files["bound_file"], files["bound_file"])

def test_shutil_copystat(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copystat(files["visible"], files["bound_file"]) is None
    shutil.copystat(files["bound_file"], files["visible"]) is None

def test_shutil_copytree_and_move(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.copytree(files["bind_dest"], files["path"]/"tmp") is None
    shutil.move(files["path"]/"tmp", files["path"]/"tmp2") is None
    shutil.rmtree(files["path"]/"tmp2")

def test_shutil_disk_usage(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.disk_usage(files["bind_dest"]) is None

def test_shutil_make_archive(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    shutil.make_archive(
        base_name=files["path"] / "arch",
        format="zip",
        root_dir=files["bind_dest"]  # dossier à compresser
    )

