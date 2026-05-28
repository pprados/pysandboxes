import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Iterator, List

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError
from pysandboxes.guard_files import FSExposeRule, activate_guard, parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, ConfigLines
from pysandboxes.tools import follow_links_executable


def _deactivate_all_rules() -> None:
    from pysandboxes.guard_api import _deactivate_guard_api
    from pysandboxes.guard_files import _deactivate_guard_files
    from pysandboxes.guard_import import _deactivate_guard_import
    from pysandboxes.guard_pickle import _deactivate_guard_pickle
    from pysandboxes.guard_socket import _deactivate_guard_sockets

    _deactivate_guard_files()
    _deactivate_guard_sockets()
    _deactivate_guard_import()
    _deactivate_guard_pickle()
    _deactivate_guard_api()


_guard_import_for_tests_activated: bool = False


def _activate_guard_import_for_tests() -> None:
    global _guard_import_for_tests_activated
    if _guard_import_for_tests_activated:
        return
    _guard_import_for_tests_activated = True
    from pysandboxes.guard_files import patch_rules as file_patch_rules
    from pysandboxes.guard_import import (
        activate_guard_import,
    )
    from pysandboxes.guard_import import (
        patch_rules as import_path_rules,
    )
    from pysandboxes.guard_socket import patch_rules as socket_path_rules

    # assert "io" not in sys.modules
    activate_guard_import(
        {
            **file_patch_rules(learn=False),
            **socket_path_rules(learn=False),
            **import_path_rules(learn=False),
        },
        ("*",),  # Import all modules
    )


def _activate_guard_import_blocking_pickle() -> None:
    """Activate guard_import with pickle BLOCKED by removing from sys.modules."""
    import sys

    # First, remove pickle from sys.modules so it's not available
    sys.modules.pop("pickle", None)
    sys.modules.pop("pickletools", None)
    sys.modules.pop("_pickle", None)

    # Then activate normally
    from pysandboxes.guard_files import patch_rules as file_patch_rules
    from pysandboxes.guard_import import (
        activate_guard_import,
    )
    from pysandboxes.guard_import import (
        patch_rules as import_path_rules,
    )
    from pysandboxes.guard_socket import patch_rules as socket_path_rules

    activate_guard_import(
        {
            **file_patch_rules(learn=False),
            **socket_path_rules(learn=False),
            **import_path_rules(learn=False),
        },
        ("*",),  # Import all modules EXCEPT pickle (which was removed above)
    )


@pytest.fixture(autouse=True)
def reset_rules() -> Iterator[None]:
    yield
    _deactivate_all_rules()


tmp_path = Path(tempfile.TemporaryDirectory(prefix="pysandboxes_test_").name)


@pytest.fixture
def files() -> Dict[str, Path]:
    # Create test files and symlinks
    # Runs without patch.
    global tmp_path
    if tmp_path.exists():
        # Remove, without sandboxes
        subprocess.run(["rm", "-rf", str(tmp_path)], check=True)
    tmp_path.mkdir(exist_ok=False)
    (tmp_path / "visible.txt").write_text("Visible")
    (tmp_path / "ignore.log").write_text("Should be ignored")
    (tmp_path / "bound.txt").write_text("Bound target")

    # Layout under a single exposed root (fs-expose): source files and a mirror dir
    bind_src = tmp_path / "bind_src"
    bind_dest = tmp_path / "bind_dest"  # FIXME
    bind_src.mkdir(exist_ok=False)
    bind_dest.mkdir(exist_ok=False)
    (bind_src / "bound_file.txt").write_text("Content")
    bf = bind_src / "bound_file.txt"
    if not (bind_dest / "bound_file.txt").exists():
        (bind_dest / "bound_file.txt").symlink_to(bf)
    if not (bind_dest / "link_to_bind_src").exists():
        (bind_dest / "link_to_bind_src").symlink_to(bf)
    if not (bind_dest / "link_relative_to_bind_src").exists():
        (bind_dest / "link_relative_to_bind_src").symlink_to("bound_file.txt")

    # Symlink to ignore.log
    if not (tmp_path / "home_link_to_ignore").exists():
        (tmp_path / "home_link_to_ignore").symlink_to(tmp_path / "ignore.log")
    if not (tmp_path / "home_link").exists():
        (tmp_path / "home_link").symlink_to(tmp_path / "visible.txt")
    if not (tmp_path / "home_link_to_bind_src").exists():
        (tmp_path / "home_link_to_bind_src").symlink_to(
            tmp_path / "bind_src/bound_file.txt"
        )
    if not (tmp_path / "home_link_relative_to_bind_src").exists():
        (tmp_path / "home_link_relative_to_bind_src").symlink_to(
            "bind_src/bound_file.txt"
        )

    if not (tmp_path / "bind_src/link_to_bind_src").exists():
        (tmp_path / "bind_src/link_to_bind_src").symlink_to(
            tmp_path / "bind_src/bound_file.txt"
        )
    if not (tmp_path / "bind_src/link_relative_to_bind_src").exists():
        (tmp_path / "bind_src/link_relative_to_bind_src").symlink_to("bound_file.txt")

    # TODO: yield and remove ?
    return {
        "path": tmp_path,
        "visible": tmp_path / "visible.txt",
        "new_link": tmp_path / "new_link",
        "ignore": tmp_path / "ignore.log",
        "bind_src": bind_src,
        "bind_dest": bind_dest,
        "bound_file": bind_src / "bound_file.txt",
        "home_link_to_ignore": tmp_path / "home_link_to_ignore",
        "home_link": tmp_path / "home_link",
        "home_link_to_bind_src": tmp_path / "home_link_to_bind_src",
        "home_link_relative_to_bind_src": tmp_path / "home_link_relative_to_bind_src",
        "link_to_bind": tmp_path / "bind_dest/link_to_bind_src",
        "new_link_to_bind": tmp_path / "bind_dest/new_link_to_bind_src",
        "link_relative_to_bind": tmp_path / "bind_dest/link_relative_to_bind_src",
        "new_link_relative_to_bind": tmp_path
        / "bind_dest/new_link_relative_to_bind_src",
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


def activate_guard_files_rules(rules: ConfigLines) -> None:
    errors: List[ErrorMsg] = []
    _deactivate_all_rules()
    file_rules, _ = parse_rules(rules, errors)
    assert not errors

    # Add more rules for pytests
    import pwd
    import sys

    new_file_rules: List[FSExposeRule] = []
    exe_paths: set[Path] = set()
    follow_links_executable(Path(sys.executable), exe_paths)
    for p in exe_paths:
        rp = Path(p).resolve()
        if rp.is_dir():
            p_str = str(rp) + "/" if rp != Path("/") else "/"
        else:
            p_str = str(rp)
        new_file_rules.append(
            FSExposeRule(
                path=p_str,
                write=True,
                config=ConfigLine("Hack for pytest", Path(), 0),
            )
        )

    import os  # noqa: F811

    username = pwd.getpwuid(os.getuid())[0]
    tmp_pytest = Path(f"/tmp/pytest-of-{username}").resolve()
    tmp_str = str(tmp_pytest) + "/" if tmp_pytest != Path("/") else "/"
    new_file_rules.append(
        FSExposeRule(
            path=tmp_str,
            write=True,
            config=ConfigLine("Hack for pytest", Path(), 0),
        )
    )
    # activate_guard(tuple(list(file_rules) + new_file_rules))
    all_rules = list(file_rules)
    all_rules.extend(new_file_rules)
    activate_guard(tuple(all_rules))


def test_io_open_ignore_rule_blocks_file_access(files: Dict[str, Path]) -> None:
    rules = [ConfigLine(f"ignore={files['ignore']}", Path(), 0)]
    activate_guard_files_rules(rules)

    import io

    with pytest.raises(RuleFileNotFoundError):
        io.open(files["ignore"])


def test_io_open_code_ignore_rule_blocks_open_code_file_access(
    files: Dict[str, Path],
) -> None:
    rules = [ConfigLine(f"ignore={files['ignore']}", Path(), 0)]
    activate_guard_files_rules(rules)

    import io

    with pytest.raises(RuleFileNotFoundError):
        io.open_code(str(files["ignore"]))


def test_io_open_expose_rule_reads_under_exposed_dirs(files: Dict[str, Path]) -> None:
    rules = [ConfigLine(f"expose-rw={files['path']}", Path(), 0)]
    activate_guard_files_rules(rules)
    target_path = files["bind_src"] / "bound_file.txt"

    import io

    with io.open(target_path) as f:
        content = f.read()
    assert content == "Content"


def test_io_open_write(files: Dict[str, Path]) -> None:
    rules = [ConfigLine(f"expose-rw={files['path']}", Path(), 0)]
    activate_guard_files_rules(rules)
    target_path = files["bind_dest"] / "write.txt"

    import io
    import os  # noqa: F811

    with io.open(target_path, "w") as f:
        f.write("sample")
    os.remove(str(target_path))


def test_io_open_refuse_write(files: Dict[str, Path]) -> None:
    rules = [ConfigLine(f"expose-ro={files['path']}", Path(), 0)]
    activate_guard_files_rules(rules)
    target_path = files["bind_dest"] / "write.txt"

    import io

    with pytest.raises(PermissionError):
        with io.open(target_path, "w") as f:
            f.write("sample")


def test_io_open_visible_and_invisible_files(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io

    with io.open(files["visible"]) as f:
        assert f.read() == "Visible"

    with pytest.raises(RuleFileNotFoundError):
        with io.open(files["ignore"]):
            pass

    with io.open(files["bind_src"] / "bound_file.txt") as f:
        assert f.read() == "Content"

    with pytest.raises((RuleFileNotFoundError, FileNotFoundError)):
        with io.open(files["bind_dest"] / "missing-bound.txt"):
            pass


def test_io_FileIO(files: Dict[str, Path]) -> None:
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import io

    with io.FileIO(files["visible"], "r") as f:
        assert f.read() == b"Visible"

    with io.FileIO(files["bind_src"] / "bound_file.txt", "r") as f:
        assert f.read() == b"Content"

    with pytest.raises(RuleFileNotFoundError):
        with io.FileIO(files["ignore"], "r"):
            pass

    with pytest.raises((RuleFileNotFoundError, FileNotFoundError)):
        with io.FileIO(files["bind_dest"] / "missing-bound.txt", "r"):
            pass
