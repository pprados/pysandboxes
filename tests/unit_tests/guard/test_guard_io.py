from pathlib import Path
from typing import Dict

import pytest

from pysandboxes import RuleFileNotFoundError
from pysandboxes.guard_files import activate_guard, parse_rules
from pysandboxes.types import ConfigLines, ConfigLine


def _reset_rules():
    from pysandboxes.guard_import import _deactivate_guard_import, \
        activate_guard_import, patch_rules as import_path_rules
    from pysandboxes.guard_files import _deactivate_guard_files, patch_rules as file_patch_rules
    from pysandboxes.guard_socket import _deactivate_guard_sockets, patch_rules as socket_path_rules
    activate_guard_import(
        {
            **file_patch_rules(),
            **socket_path_rules(),
            **import_path_rules(),
        },
        tuple(["*"]),  # Import all modules
    )
    yield
    _deactivate_guard_files()
    _deactivate_guard_sockets()
    _deactivate_guard_import()


@pytest.fixture(autouse=True)
def reset_rules():
    _reset_rules()


@pytest.fixture
def files(tmp_path) -> Dict[str, Path]:
    # Create test files and symlinks
    # It's executer without patch.
    tmp_path = Path("/tmp/test")
    tmp_path.mkdir(exist_ok=True)
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


def _activate_guard(rules: ConfigLines) -> None:
    errors = []
    file_rules, _ = parse_rules(rules, errors)
    activate_guard(file_rules)
    assert not errors


def test_io_open_ignore_rule_blocks_file_access(files: Dict[str, Path]):
    rules = [
        ConfigLine(f"ignore={files['ignore']}", Path(), 0)
    ]
    _activate_guard(rules)

    import io
    with pytest.raises(RuleFileNotFoundError):
        io.open(files['ignore'])


def test_io_open_code_ignore_rule_blocks_open_code_file_access(files: Dict[str, Path]):
    rules = [
        ConfigLine(f"ignore={files['ignore']}", Path(), 0)
    ]
    _activate_guard(rules)

    import io
    with pytest.raises(RuleFileNotFoundError):
        io.open_code(str(files['ignore']))


def test_io_open_bind_rule_redirects_file_access(files: Dict[str, Path]):
    rules = [
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0)
    ]
    _activate_guard(rules)
    # Access using the dest path should redirect to src
    target_path = files['bind_dest'] / "bound_file.txt"

    import io
    with io.open(target_path) as f:
        content = f.read()
    assert content == "Content"


def test_io_open_write(files: Dict[str, Path]):
    rules = [
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0)
    ]
    _activate_guard(rules)
    target_path = files['bind_dest'] / "write.txt"

    import io
    import os
    with io.open(target_path, "w") as f:
        f.write("sample")
    os.remove(str(target_path))


def test_io_open_refuse_write(files: Dict[str, Path]):
    rules = [
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0)
    ]
    _activate_guard(rules)
    target_path = files['bind_dest'] / "write.txt"

    import io
    with pytest.raises(PermissionError):
        with io.open(target_path, "w") as f:
            f.write("sample")


def test_io_open_visible_and_invisible_files(files: Dict[str, Path]):
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    _activate_guard(rules)

    import io
    with io.open(files['visible']) as f:
        assert f.read() == "Visible"

    with pytest.raises(RuleFileNotFoundError):
        with io.open(files['ignore']):
            pass

    with io.open(files['bind_dest'] / "bound_file.txt"):
        pass

    with pytest.raises(RuleFileNotFoundError):
        with io.open(files['bind_src'] / "bound_file.txt"):
            pass


def test_io_FileIO(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    _activate_guard(rules)

    import io
    with io.FileIO(files['visible'], "r") as f:
        assert f.read() == b"Visible"

    with io.FileIO(files['bind_dest'] / "bound_file.txt", "r"):
        pass

    with pytest.raises(RuleFileNotFoundError):
        with io.FileIO(files['ignore'], "r"):
            pass

    with pytest.raises(RuleFileNotFoundError):
        with io.FileIO(files['bind_src'], "r"):
            pass
