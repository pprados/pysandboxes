from pathlib import Path

import pytest

from pysandboxes.sb_types import ConfigLine
from .test_guard_io import files, activate_guard_files_rules, _reset_rules


def test_os_path_abspath(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.abspath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.abspath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")


def test_os_path_exists_and_lexists(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.exists(files["path"] / "visible.txt")
    assert os.path.exists(files["bind_dest"] / "bound_file.txt")
    assert os.path.lexists(files["path"] / "visible.txt")
    assert os.path.lexists(files["bind_dest"] / "bound_file.txt")


def test_os_path_islink(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert not os.path.islink(files["path"] / "visible.txt")
    assert os.path.islink(files["home_link"])
    assert not os.path.islink(files["bind_dest"] / "bound_file.txt")


def test_os_path_isdir(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.isdir(files["path"])
    assert os.path.isdir(files["bind_dest"])


def test_os_path_isfile(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.isfile(files["path"] / "visible.txt")
    assert os.path.isfile(files["bind_dest"] / "bound_file.txt")


def test_os_path_samefile(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.samefile(files["path"] / "visible.txt",
                            files["path"] / "visible.txt") is True
    os.stat(files["bind_dest"] / "bound_file.txt")
    assert os.path.samefile(files["bind_dest"] / "bound_file.txt",
                            files["bind_dest"] / "bound_file.txt") is True
    assert os.path.samefile(files["path"] / "visible.txt",
                            files["bound_file"]) is False


def test_os_path_realpath(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.realpath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.realpath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")


def test_os_path_atime_mtime_ctime_and_size(files):
    rules = [
        ConfigLine(f"ignore=*.log",Path(),0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    activate_guard_files_rules(rules)

    import os
    assert os.path.getatime(files["path"] / "visible.txt")
    assert os.path.getatime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getmtime(files["path"] / "visible.txt")
    assert os.path.getmtime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getctime(files["path"] / "visible.txt")
    assert os.path.getctime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getsize(files["path"] / "visible.txt")
    assert os.path.getsize(files["bind_dest"] / "bound_file.txt")
