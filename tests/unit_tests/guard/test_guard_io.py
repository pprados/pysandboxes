import io
import os
import pathlib

import pytest

from pysandboxes.guard_files import activate_guard_files, parse_rules, \
    RuleFileNotFoundError


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_files import _deactivate_guard_files

    yield
    _deactivate_guard_files()


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
        "new_link": tmp_path / "new_link",
        "ignore": tmp_path / "ignore.log",
        "bind_src": bind_src,
        "bind_dest": bind_dest,
        "bound_file": bind_dest / "bound_file.txt",
        "home_link_to_ignore": tmp_path / "home_link_to_ignore",
        "home_link": tmp_path / "home_link",
        "home_link_to_bind_src": tmp_path / "home_link_to_bind_src",
        "home_link_relative_to_bind_src": tmp_path / "home_link_relative_to_bind_src",
        "link_to_bind": tmp_path / "bind_dest/link_to_bind_src",
        "new_link_to_bind": tmp_path / "bind_dest/new_link_to_bind_src",
        "link_relative_to_bind": tmp_path / "bind_dest/link_relative_to_bind_src",
        "new_link_relative_to_bind": tmp_path / "bind_dest/new_link_relative_to_bind_src",
        "to_rename": tmp_path / "to_rename.txt",
        "new_rename": tmp_path / "new_rename.txt",
        "bind_to_rename": tmp_path / "bind_dest/to_rename.txt",
        "new_bind_rename": tmp_path / "bind_dest/new_rename.txt",
        "to_replace": tmp_path / "to_replace.txt",
        "new_replace": tmp_path / "new_replace.txt",
        "bind_to_replace": tmp_path / "bind_dest/to_rename.txt",
        "new_bind_replace": tmp_path / "bind_dest/new_replace.txt",
        "to_truncate": tmp_path / "to_truncate.txt",
        "bind_to_truncate": tmp_path / "bind_dest/to_truncate.txt",
    }


def str_activate_guard_files(rules: ConfigLines) -> None:
    file_rules, _ = parse_rules(rules)
    activate_guard_files(file_rules)


def test_io_open_ignore_rule_blocks_file_access(files):
    rules = [f"--ignore={files['ignore']}"]
    str_activate_guard_files(rules)

    with pytest.raises(RuleFileNotFoundError):
        io.open(files['ignore'])


def test_io_open_code_ignore_rule_blocks_open_code_file_access(files):
    rules = [f"--ignore={files['ignore']}"]
    str_activate_guard_files(rules)
    with pytest.raises(RuleFileNotFoundError):
        io.open_code(str(files['ignore']))


def test_io_open_bind_rule_redirects_file_access(files):
    rules = [f"--bind={files['bind_src']},{files['bind_dest']}"]
    str_activate_guard_files(rules)
    # Access using the dest path should redirect to src
    target_path = files['bind_dest'] / "bound_file.txt"
    with io.open(target_path) as f:
        content = f.read()
    assert content == "Content"


def test_io_open_write(files):
    rules = [f"--bind={files['bind_src']},{files['bind_dest']}"]
    str_activate_guard_files(rules)
    target_path = files['bind_dest'] / "write.txt"
    with io.open(target_path, "w") as f:
        f.write("sample")
    os.remove(str(target_path))


def test_io_open_refuse_write(files):
    rules = [f"--ro-bind={files['bind_src']},{files['bind_dest']}"]
    str_activate_guard_files(rules)
    target_path = files['bind_dest'] / "write.txt"
    with pytest.raises(PermissionError):
        with io.open(target_path, "w") as f:
            f.write("sample")


def test_io_open_visible_file_is_accessible(files):
    rules = ["--ignore=*.log"]
    str_activate_guard_files(rules)
    with open(files['visible']) as f:
        assert f.read() == "Visible"
