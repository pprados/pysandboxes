import pathlib as opl
import stat
from typing import Any, Dict, List

import pytest

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)

NonePath = opl.Path()


def test_pathlib_open(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]

    activate_guard_files_rules(rules)

    import pathlib

    with pathlib.Path(
        files["visible"]
    ).open() as f:  # Need to use new Path() implementation
        f.read()
    with pathlib.Path(files["bound_file"]).open() as f:
        f.read()


def test_pathlib_read_write_text(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]

    activate_guard_files_rules(rules)

    import pathlib

    pathlib.Path(files["path"] / "to_write.txt").write_text("To write")
    assert pathlib.Path(files["path"] / "to_write.txt").read_text() == "To write"
    pathlib.Path(files["bind_dest"] / "to_write.txt").write_text("To write")
    assert pathlib.Path(files["bind_dest"] / "to_write.txt").read_text() == "To write"


def test_pathlib_read_write_bytes(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    (files["path"] / "to_write.txt").write_bytes("To write".encode())
    assert pathlib.Path(files["path"] / "to_write.txt").read_text() == "To write"
    (files["bind_dest"] / "to_write.txt").write_bytes("To write".encode())
    assert pathlib.Path(files["bind_dest"] / "to_write.txt").read_text() == "To write"


def test_pathlib_is(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(files["path"] / "to_write.txt").is_absolute()
    assert pathlib.Path(files["bind_dest"] / "to_write.txt").is_absolute()
    assert not pathlib.Path(files["path"] / "to_write.txt").is_block_device()
    assert not pathlib.Path(files["bind_dest"] / "to_write.txt").is_block_device()
    assert not pathlib.Path(files["path"] / "to_write.txt").is_char_device()
    assert not pathlib.Path(files["bind_dest"] / "to_write.txt").is_char_device()
    assert not pathlib.Path(files["path"] / "to_write.txt").is_fifo()
    assert not pathlib.Path(files["bind_dest"] / "to_write.txt").is_fifo()
    assert pathlib.Path(files["path"]).is_dir()
    assert pathlib.Path(files["bind_dest"]).is_dir()
    assert pathlib.Path(files["path"] / "visible.txt").is_file()
    assert pathlib.Path(files["bind_dest"] / "bound_file.txt").is_file()
    assert not pathlib.Path(files["path"]).is_mount()
    assert not pathlib.Path(files["bind_dest"]).is_mount()
    assert not pathlib.Path(files["path"]).is_junction()
    assert not pathlib.Path(files["bind_dest"]).is_junction()
    assert pathlib.Path(files["path"]).is_relative_to(files["path"])
    assert pathlib.Path(files["bind_dest"]).is_relative_to(files["bind_dest"])
    assert not pathlib.Path(files["path"]).is_reserved()
    assert not pathlib.Path(files["bind_dest"]).is_reserved()
    assert not pathlib.Path(files["path"]).is_socket()
    assert not pathlib.Path(files["bind_dest"]).is_socket()
    assert pathlib.Path(files["home_link"]).is_symlink()
    assert not pathlib.Path(files["bind_dest"] / "bound_file.txt").is_symlink()
    assert pathlib.Path(files["bind_dest"] / "bound_file.txt").exists() is True


def test_pathlib_info(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(files["path"]).owner()
    assert pathlib.Path(files["path"]).group()
    assert pathlib.Path(files["bind_dest"]).owner()
    assert pathlib.Path(files["bind_dest"]).group()


def test_pathlib_glob(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
        ConfigLine("ro-bind=./pysandboxes,./pysandboxes", NonePath, 0),
    ]
    activate_guard_files_rules(rules)
    import pathlib

    result: List[Any]

    result = [f for f in pathlib.Path("pysandboxes").glob("**/*.template")]
    assert pathlib.Path("templates/py-sandbox.template") in result

    result = [pathlib.Path(f).name for f in pathlib.Path(files["path"]).glob("*")]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

    result = [pathlib.Path(f).name for f in pathlib.Path(files["bind_dest"]).glob("*")]
    assert "bound_file.txt" in result


def test_pathlib_rglob(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    result = list(pathlib.Path(files["path"]).rglob("*"))
    assert pathlib.Path(files["path"] / "ignore.log") not in result
    assert pathlib.Path(files["path"] / "visible.txt") in result
    assert pathlib.Path(files["bind_dest"] / "bound_file.txt") in result


def test_pathlib_iterdir(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    result = [f.name for f in pathlib.Path(files["path"]).iterdir()]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

    result = [f.name for f in pathlib.Path(files["bind_dest"]).iterdir()]
    assert "bound_file.txt" in result

    path = pathlib.Path(files["path"])
    rc = list(path.iterdir())
    assert files["bind_src"] not in rc
    assert files["ignore"] not in rc
    assert files["bind_dest"] in rc


def test_pathlib_chmod_and_lchmod(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    mode = pathlib.Path(files["path"]).stat().st_mode
    pathlib.Path(files["path"]).chmod(mode | stat.S_IREAD)
    pathlib.Path(files["bind_dest"] / "bound_file.txt").chmod(mode | stat.S_IREAD)
    pathlib.Path(files["path"]).lchmod(mode | stat.S_IREAD)
    pathlib.Path(files["bind_dest"] / "bound_file.txt").lchmod(mode | stat.S_IREAD)


def test_pathlib_statand_stat_and_lstat(
    files: Dict[str, opl.Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(files["visible"]).stat()
    with pytest.raises(RuleFileNotFoundError):
        assert pathlib.Path(files["ignore"]).stat()
    assert pathlib.Path(files["home_link"]).stat(follow_symlinks=True)
    assert pathlib.Path(files["bind_dest"] / "bound_file.txt").stat(
        follow_symlinks=True
    )

    assert pathlib.Path(files["home_link"]).lstat()
    assert pathlib.Path(files["bind_dest"] / "bound_file.txt").lstat()


def test_pathlib_mkdir_removedirs_and_rmdir(
    files: Dict[str, opl.Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    pathlib.Path(files["path"] / "dir_to_remove").mkdir()
    pathlib.Path(files["path"] / "dir_to_remove").rmdir()

    pathlib.Path(files["bind_dest"] / "dir_to_remove").mkdir()
    pathlib.Path(files["bind_dest"] / "dir_to_remove").rmdir()


def test_pathlib_link_symlink_and_readlink(
    files: Dict[str, opl.Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(files["home_link"]).readlink() == pathlib.Path(files["visible"])
    assert pathlib.Path(files["home_link_to_bind_src"]).readlink() == pathlib.Path(
        files["bound_file"]
    )
    assert pathlib.Path(
        files["home_link_relative_to_bind_src"]
    ).readlink() == pathlib.Path(files["bound_file"])
    assert pathlib.Path(
        files["bind_dest"] / "link_to_bind_src"
    ).readlink() == pathlib.Path(files["bound_file"])
    assert pathlib.Path(files["link_to_bind"]).readlink() == pathlib.Path(
        files["bound_file"]
    )
    assert pathlib.Path(files["link_relative_to_bind"]).readlink() == pathlib.Path(
        files["bound_file"]
    )
    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["home_link_to_ignore"]).readlink()

    files["new_link"].unlink(missing_ok=True)
    pathlib.Path(files["new_link"]).hardlink_to(files["visible"])
    assert pathlib.Path(files["new_link"]).exists() is True
    pathlib.Path(files["new_link"]).unlink()

    files["new_link_to_bind"].unlink(missing_ok=True)
    pathlib.Path(files["new_link_to_bind"]).hardlink_to(files["bound_file"])
    assert pathlib.Path(files["new_link_to_bind"]).exists() is True
    pathlib.Path(files["new_link_to_bind"]).unlink()

    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["new_link"]).hardlink_to(files["bind_src"] / "toto")

    files["new_link"].unlink(missing_ok=True)
    pathlib.Path(files["new_link"]).symlink_to(files["visible"])
    assert pathlib.Path(files["new_link"]).exists() is True
    assert pathlib.Path(files["new_link"]).readlink() == pathlib.Path(files["visible"])
    pathlib.Path(files["new_link"]).unlink()

    files["new_link_to_bind"].unlink(missing_ok=True)
    pathlib.Path(files["new_link_to_bind"]).symlink_to(
        pathlib.Path(files["bound_file"])
    )
    assert pathlib.Path(files["new_link_to_bind"]).exists() is True
    assert pathlib.Path(files["new_link_to_bind"]).readlink() == pathlib.Path(
        files["bound_file"]
    )
    pathlib.Path(files["new_link_to_bind"]).unlink()

    # Link to unknown file
    pathlib.Path(files["new_link"]).symlink_to(pathlib.Path(files["bind_src"] / "toto"))


def test_pathlib_link_symlink_and_readlink_refused(
    files: Dict[str, opl.Path],  # noqa: F811
) -> None:
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    with pytest.raises(PermissionError):
        pathlib.Path(files["bound_file"]).hardlink_to(files["visible"])


def test_pathlib_touch(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    pathlib.Path(files["path"]).touch()
    pathlib.Path(files["bind_dest"] / "bound_file.txt").touch()
    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["ignore"]).touch()
    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["bind_src"]).touch()


def test_pathlib_touch_refused(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    with pytest.raises(PermissionError):
        pathlib.Path(files["bound_file"]).touch()


def test_pathlib_rename(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    pathlib.Path(files["to_rename"]).write_text("To rename")
    assert pathlib.Path(files["to_rename"]).rename(
        pathlib.Path(files["new_rename"])
    ) == pathlib.Path(files["new_rename"])
    pathlib.Path(files["new_rename"]).unlink()

    pathlib.Path(files["bind_to_rename"]).write_text("To rename")
    assert pathlib.Path(files["bind_to_rename"]).rename(
        files["new_bind_rename"]
    ) == pathlib.Path(files["new_bind_rename"])
    pathlib.Path(files["new_bind_rename"]).unlink()

    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["ignore"]).rename(pathlib.Path(files["ignore"]))
    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["bind_src"]).rename(pathlib.Path(files["bind_src"]))


def test_pathlib_rename_refused(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    with pytest.raises(PermissionError):
        pathlib.Path(files["bound_file"]).rename(files["bind_dest"] / "new_rename")


def test_pathlib_replace(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    pathlib.Path(files["to_replace"]).write_text("To replace")
    pathlib.Path(files["to_replace"]).replace(files["new_replace"])
    pathlib.Path(files["new_replace"]).unlink()

    pathlib.Path(files["bind_to_replace"]).write_text("To replace")
    pathlib.Path(files["bind_to_replace"]).replace(files["new_bind_replace"])
    pathlib.Path(files["new_bind_replace"]).unlink()

    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["ignore"]).replace(files["new_replace"])

    with pytest.raises(RuleFileNotFoundError):
        pathlib.Path(files["bind_src"]).replace(files["new_replace"])


def test_pathlib_replace_refused(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    with pytest.raises(PermissionError):
        pathlib.Path(files["bound_file"]).replace(files["bind_dest"] / "new_replace")


def test_pathlib_resolve(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(
        files["bind_dest"] / ".." / "visible.txt"
    ).resolve() == pathlib.Path(files["visible"])


def test_pathlib_samefile(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    assert pathlib.Path(files["visible"]).samefile(pathlib.Path(files["visible"]))
    assert pathlib.Path(files["bound_file"]).samefile(pathlib.Path(files["bound_file"]))
    with pytest.raises(RuleFileNotFoundError):
        assert pathlib.Path(files["ignore"]).samefile(pathlib.Path(files["ignore"]))


def test_pathlib_walk(files: Dict[str, opl.Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", NonePath, 0),
        ConfigLine(f"ro-bind={files['path']},{files['path']}", NonePath, 0),
        ConfigLine(f"ro-bind={files['bind_src']},{files['bind_dest']}", NonePath, 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib

    rc = list(pathlib.Path(files["path"]).walk())
    assert rc[0][0] == pathlib.Path(files["path"])
    assert "bind_src" not in rc[0][1]
    assert "bind_dest" in rc[0][1]
    assert rc[1][0] == pathlib.Path(files["bind_dest"])
    assert "bound_file.txt" in rc[1][2]

    rc = list(pathlib.Path(files["bind_dest"]).walk())
    assert rc[0][0] == pathlib.Path(files["bind_dest"])
    assert "bound_file.txt" in rc[0][2]
