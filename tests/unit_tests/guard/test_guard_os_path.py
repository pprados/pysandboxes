from pathlib import Path

import pytest

from pysandboxes.types import ConfigLine
from .test_guard_io import files, _activate_guard


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_import import conv_patch_rules, _deactivate_guard_import, \
        activate_guard_import
    from pysandboxes.guard_files import _deactivate_guard_files, patch_rules
    activate_guard_import(
        conv_patch_rules(
            {
                **patch_rules(),
            }
        ),
        tuple(["*"]),  # Import all modules
    )
    yield
    _deactivate_guard_files()
    _deactivate_guard_import()



def test_os_path_abspath(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.abspath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.abspath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")


def test_os_path_exists_and_lexists(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.exists(files["path"] / "visible.txt")
    assert os.path.exists(files["bind_dest"] / "bound_file.txt")
    assert os.path.lexists(files["path"] / "visible.txt")
    assert os.path.lexists(files["bind_dest"] / "bound_file.txt")


def test_os_path_islink(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert not os.path.islink(files["path"] / "visible.txt")
    assert os.path.islink(files["home_link"])
    assert not os.path.islink(files["bind_dest"] / "bound_file.txt")


def test_os_path_isdir(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.isdir(files["path"])
    assert os.path.isdir(files["bind_dest"])


def test_os_path_isfile(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.isfile(files["path"] / "visible.txt")
    assert os.path.isfile(files["bind_dest"] / "bound_file.txt")


def test_os_path_samefile(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.samefile(files["path"] / "visible.txt",
                            files["path"] / "visible.txt")
    assert os.path.samefile(files["bind_dest"] / "bound_file.txt",
                            files["bind_dest"] / "bound_file.txt")


def test_os_path_realpath(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.realpath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.realpath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")


def test_os_path_atime_mtime_ctime_and_size(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    _activate_guard(rules)

    import os
    assert os.path.getatime(files["path"] / "visible.txt")
    assert os.path.getatime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getmtime(files["path"] / "visible.txt")
    assert os.path.getmtime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getctime(files["path"] / "visible.txt")
    assert os.path.getctime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getsize(files["path"] / "visible.txt")
    assert os.path.getsize(files["bind_dest"] / "bound_file.txt")
