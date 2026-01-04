import os
import pytest

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
from test_guard_io import files


@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import _deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    _deactivate_guard_files()


def test_os_path_abspath(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.abspath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.abspath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")


def test_os_path_exists_and_lexists(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.exists(files["path"] / "visible.txt")
    assert os.path.exists(files["bind_dest"] / "bound_file.txt")
    assert os.path.lexists(files["path"] / "visible.txt")
    assert os.path.lexists(files["bind_dest"] / "bound_file.txt")


def test_os_path_islink(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert not os.path.islink(files["path"] / "visible.txt")
    assert os.path.islink(files["home_link"])
    assert not os.path.islink(files["bind_dest"] / "bound_file.txt")


def test_os_path_isdir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.isdir(files["path"])
    assert os.path.isdir(files["bind_dest"])


def test_os_path_isfile(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.isfile(files["path"] / "visible.txt")
    assert os.path.isfile(files["bind_dest"] / "bound_file.txt")


def test_os_path_samefile(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.samefile(files["path"] / "visible.txt",
                            files["path"] / "visible.txt")
    assert os.path.samefile(files["bind_dest"] / "bound_file.txt",
                            files["bind_dest"] / "bound_file.txt")


def test_os_path_realpath(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.realpath(files["path"] / "visible.txt") == str(
        files["path"] / "visible.txt")
    assert os.path.realpath(files["bind_dest"] / "bound_file.txt") == str(
        files["bind_dest"] / "bound_file.txt")

def test_os_path_atime_mtime_ctime_and_size(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    assert os.path.getatime(files["path"] / "visible.txt")
    assert os.path.getatime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getmtime(files["path"] / "visible.txt")
    assert os.path.getmtime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getctime(files["path"] / "visible.txt")
    assert os.path.getctime(files["bind_dest"] / "bound_file.txt")
    assert os.path.getsize(files["path"] / "visible.txt")
    assert os.path.getsize(files["bind_dest"] / "bound_file.txt")
