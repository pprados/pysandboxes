from io import open_code

import os
import pathlib
import pytest

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files


@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import activate_guard_files, \
        deactivate_guard_files

    yield
    print("desactivate")
    deactivate_guard_files()

@pytest.fixture
def temp_files(tmp_path):
    # Create test files and symlinks
    tmp_path= pathlib.Path("/tmp/ppr");tmp_path.mkdir(exist_ok=True)  # FIXME: remove this line
    (tmp_path / "visible.txt").write_text("Visible")
    (tmp_path / "ignore.log").write_text("Should be ignored")
    (tmp_path / "bound.txt").write_text("Bound target")

    # Symlink to ignore.log
    if not (tmp_path / "link_to_ignore").exists():
        (tmp_path / "link_to_ignore").symlink_to(tmp_path / "ignore.log")

    # Create a bind destination
    bind_src = tmp_path / "bind_src"
    bind_dest = tmp_path / "bind_dest"
    bind_src.mkdir(exist_ok=True)
    bind_dest.mkdir(exist_ok=True)
    (bind_src / "bound_file.txt").write_text("Content")

    return {
        "visible": tmp_path / "visible.txt",
        "ignore": tmp_path / "ignore.log",
        "link_to_ignore": tmp_path / "link_to_ignore",
        "bind_src": bind_src,
        "bind_dest": bind_dest,
        "bound_file": bind_src / "bound_file.txt"
    }


def test_ignore_rule_blocks_file_access(temp_files):
    rules = [f"--ignore={temp_files['ignore']}"]
    activate_guard_files(rules)

    with pytest.raises(FileNotFoundError):
        open(temp_files['ignore'])

@pytest.mark.skip(reason="TODO")  # TODO
def test_ignore_rule_blocks_open_code_file_access(temp_files):
    rules = [f"--ignore={temp_files['ignore']}"]
    activate_guard_files(rules)
    with pytest.raises(FileNotFoundError):
        open_code(str(temp_files['ignore']))


def test_symlink_to_ignored_file(temp_files):  # FIXME: vérifier plus profond
    rules = [f"--ignore={temp_files['ignore']}"]
    activate_guard_files(rules)
    with pytest.raises(FileNotFoundError):
        open(temp_files['link_to_ignore'])


def test_listdir_filters_ignored_files(temp_files):
    rules = [f"--ignore=*.log"]
    activate_guard_files(rules)
    entries = os.listdir(temp_files['ignore'].parent)
    assert "ignore.log" not in entries


def test_listdir_filters_ignored_files_and_bind(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['ignore'].parent},{temp_files['bind_dest']}"
    ]
    activate_guard_files(rules)
    entries = os.listdir(temp_files['bind_dest'])
    assert "ignore.log" not in entries
    assert "bound.txt" in entries
    assert "visible.txt" in entries


def test_bind_rule_redirects_file_access(temp_files):
    rules = [f"--bind={temp_files['bind_src']},{temp_files['bind_dest']}"]
    activate_guard_files(rules)
    # Access using the dest path should redirect to src
    target_path = temp_files['bind_dest'] / "bound_file.txt"
    with open(target_path) as f:
        content = f.read()
    assert content == "Content"


def test_bind_home_file_access(temp_files):
    rules = [
        f"--bind={temp_files['bind_src']},/data",
        f"--bind={temp_files['bind_src']},/",
    ]
    activate_guard_files(rules)
    # Access using the dest path should redirect to src
    with open("/bound_file.txt") as f:
        content = f.read()
    with open("/data/bound_file.txt") as f:
        content = f.read()
    assert content == "Content"
    entries = os.listdir("/")
    assert "bound_file.txt" in entries


def test_visible_file_is_accessible(temp_files):
    rules = ["--ignore=*.log"]
    activate_guard_files(rules)
    with open(temp_files['visible']) as f:
        assert f.read() == "Visible"


def test_scandir(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['ignore'].parent},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)
    with os.scandir(temp_files['bind_dest']) as scandir_it:
        entries = [entry.name for entry in scandir_it]
    assert "ignore.log" not in entries
    assert "visible.txt" in entries

def test_pathlib_glob(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['ignore'].parent},{temp_files['bind_dest']}",
    ]

    activate_guard_files(rules)

    from pathlib import Path
    result=[Path(f).name for f in temp_files['bind_dest'].glob("*")]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

def test_pathlib_api(temp_files):
    rules = [
        f"--ignore=*.log",
        f"--bind={temp_files['ignore'].parent},{temp_files['bind_dest']}",
    ]
    activate_guard_files(rules)

    from pathlib import Path
    # with Path(temp_files["visible"]).open(
    #         mode='r', buffering=-1, encoding=None,
    #         errors=None, newline=None) as f:
    #     assert f.read() == "Visible"
    #
    # assert Path(temp_files["visible"]).read_text(
    #         encoding=None,
    #         errors=None) == "Visible"
    #
    # assert Path(temp_files["visible"]).read_bytes() == str.encode("Visible")

    result=[f.name for f in Path(temp_files['bind_dest']).iterdir()]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

    # pathlib.Path.write_text = _wrap_open(pathlib.Path.open)  # type: ignore
    # pathlib.Path.write_bytes = _wrap_open(pathlib.Path.open)  # type: ignore
    # pathlib.Path.iterdir = _wrap_open(pathlib.Path.open)  # type: ignore
    # pathlib.Path.glob = _wrap_open(pathlib.Path.open)  # type: ignore
    # pathlib.Path.rglob = _wrap_open(pathlib.Path.open)  # type: ignore
    # pathlib.Path.walk = _wrap_open(pathlib.Path.open)  # type: ignore
