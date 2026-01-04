import os
import pathlib
import pytest
import io

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files


@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    deactivate_guard_files()


@pytest.fixture
def files(tmp_path):
    # Create test files and symlinks
    tmp_path = pathlib.Path("/tmp/ppr");
    tmp_path.mkdir(exist_ok=True)  # FIXME: remove this line
    (tmp_path / "visible.txt").write_text("Visible")
    (tmp_path / "ignore.log").write_text("Should be ignored")
    (tmp_path / "bound.txt").write_text("Bound target")

    # Create a bind destination
    bind_src = tmp_path / "bind_src"
    bind_dest = tmp_path / "bind_dest"
    bind_src.mkdir(exist_ok=True)
    bind_dest.mkdir(exist_ok=True)
    (bind_src / "bound_file.txt").write_text("Content")

    # Symlink to ignore.log
    if not (tmp_path / "home_link_to_ignore").exists(follow_symlinks=False):
        (tmp_path / "home_link_to_ignore").symlink_to(tmp_path / "ignore.log")
    if not (tmp_path / "home_link").exists(follow_symlinks=False):
        (tmp_path / "home_link").symlink_to(tmp_path / "visible.txt")
    if not (tmp_path / "home_link_to_bind_src").exists(follow_symlinks=False):
        (tmp_path / "home_link_to_bind_src").symlink_to(
            tmp_path / "bind_src/bound_file.txt")
    if not (tmp_path / "home_link_relative_to_bind_src").exists(follow_symlinks=False):
        (tmp_path / "home_link_relative_to_bind_src").symlink_to(
            "bind_src/bound_file.txt")

    if not (tmp_path / "bind_src/link_to_bind_src").exists(follow_symlinks=False):
        (tmp_path / "bind_src/link_to_bind_src").symlink_to(
            tmp_path / "bind_src/bound_file.txt")
    if not (tmp_path / "bind_src/link_relative_to_bind_src").exists(
            follow_symlinks=False):
        (tmp_path / "bind_src/link_relative_to_bind_src").symlink_to("bound_file.txt")

    return {
        "path": tmp_path,
        "visible": tmp_path / "visible.txt",
        "ignore": tmp_path / "ignore.log",
        "bind_src": bind_src,
        "bind_dest": bind_dest,
        "bound_file": bind_src / "bound_file.txt",
        "home_link_to_ignore": tmp_path / "home_link_to_ignore",
        "home_link": tmp_path / "home_link",
        "home_link_to_bind_src": tmp_path / "home_link_to_bind_src",
        "home_link_relative_to_bind_src": tmp_path / "home_link_relative_to_bind_src",
        "link_to_bind_src": tmp_path / "bind_src/link_to_bind_src",
        "link_relative_to_bind_src": tmp_path / "bind_src/link_relative_to_bind_src",
    }


def test_io_open_ignore_rule_blocks_file_access(files):
    rules = [f"--ignore={files['ignore']}"]
    activate_guard_files(rules)

    with pytest.raises(FileNotFoundError):
        io.open(files['ignore'])


@pytest.mark.skip(reason="TODO")  # TODO
def test_io_open_code_ignore_rule_blocks_open_code_file_access(files):
    rules = [f"--ignore={files['ignore']}"]
    activate_guard_files(rules)
    with pytest.raises(FileNotFoundError):
        io.open_code(str(files['ignore']))


def test_io_open_symlink_to_ignored_file(files):  # FIXME: vérifier plus profond
    rules = [f"--ignore={files['ignore']}"]
    activate_guard_files(rules)
    with pytest.raises(FileNotFoundError):
        io.open(files['home_link_to_ignore'])

def test_io_open_bind_rule_redirects_file_access(files):
    rules = [f"--bind={files['bind_src']},{files['bind_dest']}"]
    activate_guard_files(rules)
    # Access using the dest path should redirect to src
    target_path = files['bind_dest'] / "bound_file.txt"
    with io.open(target_path) as f:
        content = f.read()
    assert content == "Content"

def test_io_open_visible_file_is_accessible(files):
    rules = ["--ignore=*.log"]
    activate_guard_files(rules)
    with open(files['visible']) as f:
        assert f.read() == "Visible"


