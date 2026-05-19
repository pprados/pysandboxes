import sys
from pathlib import Path
from typing import Any, Dict

import pytest  # type: ignore[import-untyped]

from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


@pytest.mark.skip(reason="not implemented")
def test_shutil_chown(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import shutil

    uid = os.stat(files["bind_dest"]).st_uid
    gid = os.stat(files["bind_dest"]).st_gid

    shutil.chown(files["bind_dest"], uid, gid)


def test_shutil_copy(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.copy(files["visible"], files["new_replace"])
    files["new_replace"].unlink()
    shutil.copy(files["bound_file"], files["new_replace"])
    files["new_replace"].unlink()


def test_shutil_copy2(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib
    import shutil

    shutil.copy2(files["visible"], files["new_replace"])
    files["new_replace"].unlink()
    shutil.copy2(files["bound_file"], files["new_replace"])
    files["new_replace"].unlink()
    out = files["bind_dest"] / "copy.txt"
    assert shutil.copy2(files["bound_file"], out) is out
    pathlib.Path(out).unlink()


def test_shutil_copyfile(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
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


def test_shutil_copymode(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.copymode(files["visible"], files["bound_file"])
    shutil.copymode(files["bound_file"], files["bound_file"])


def test_shutil_copystat(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.copystat(files["visible"], files["bound_file"])
    shutil.copystat(files["bound_file"], files["visible"])


def test_shutil_copytree_and_move(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    if (files["path"] / "tmp").exists():
        shutil.rmtree(files["path"] / "tmp")
    if (files["path"] / "tmp2").exists():
        shutil.rmtree(files["path"] / "tmp2")
    shutil.copytree(files["bind_src"], files["path"] / "tmp")
    shutil.move(files["path"] / "tmp", files["path"] / "tmp2")
    shutil.rmtree(files["path"] / "tmp2")


def test_shutil_disk_usage(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.disk_usage(files["bind_dest"])


def test_shutil_make_archive(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.make_archive(
        base_name=str(files["path"] / "arch"),
        format="zip",
        root_dir=files["bind_dest"],  # dossier à compressor
    )


def test_shutil_rmtree(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    d = files["path"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    extra: dict[str, Any] = {}
    if sys.version_info[:2] > (3, 11):
        extra = {"onexc": None, "dir_fd": None}
    shutil.rmtree(d, ignore_errors=False, onerror=None, **extra)

    d = files["bind_dest"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    shutil.rmtree(d, ignore_errors=False, onerror=None, **extra)


def test_shutil_move(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    s = files["path"] / "dir_to_move"
    d = files["path"] / "dir_moved"
    if s.exists():
        shutil.rmtree(s)
    if d.exists():
        shutil.rmtree(d)

    s.mkdir()
    (s / "inner").mkdir()
    shutil.move(s, d, copy_function=shutil.copy2)
