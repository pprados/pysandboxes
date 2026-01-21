import stat
from pathlib import Path

import pytest

from pysandboxes.guard_files import RuleFileNotFoundError
from pysandboxes.types import ConfigLine
from .test_guard_io import files, str_activate_guard_files


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_files import _deactivate_guard_files

    yield
    _deactivate_guard_files()


def test_pathlib_open(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    with (files["visible"]).open() as f:
        f.read()
    with (files["bound_file"]).open() as f:
        f.read()


def test_pathlib_read_write_text(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    (files["path"] / "to_write.txt").write_text("To write")
    assert Path(files["path"] / "to_write.txt").read_text() == "To write"
    (files["bind_dest"] / "to_write.txt").write_text("To write")
    assert Path(files["bind_dest"] / "to_write.txt").read_text() == "To write"


def test_pathlib_read_write_bytes(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    (files["path"] / "to_write.txt").write_bytes("To write".encode())
    assert Path(files["path"] / "to_write.txt").read_text() == "To write"
    (files["bind_dest"] / "to_write.txt").write_bytes("To write".encode())
    assert Path(files["bind_dest"] / "to_write.txt").read_text() == "To write"


def test_pathlib_is(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    assert (files["path"] / "to_write.txt").is_absolute()
    assert (files["bind_dest"] / "to_write.txt").is_absolute()
    assert not (files["path"] / "to_write.txt").is_block_device()
    assert not (files["bind_dest"] / "to_write.txt").is_block_device()
    assert not (files["path"] / "to_write.txt").is_char_device()
    assert not (files["bind_dest"] / "to_write.txt").is_char_device()
    assert not (files["path"] / "to_write.txt").is_fifo()
    assert not (files["bind_dest"] / "to_write.txt").is_fifo()
    assert (files["path"]).is_dir()
    assert (files["bind_dest"]).is_dir()
    assert (files["path"] / "to_write.txt").is_file()
    assert (files["bind_dest"] / "to_write.txt").is_file()
    assert not (files["path"]).is_mount()
    assert not (files["bind_dest"]).is_mount()
    assert not (files["path"]).is_junction()
    assert not (files["bind_dest"]).is_junction()
    assert (files["path"]).is_relative_to(files["path"])
    assert (files["bind_dest"]).is_relative_to(files["bind_dest"])
    assert not (files["path"]).is_reserved()
    assert not (files["bind_dest"]).is_reserved()
    assert not (files["path"]).is_socket()
    assert not (files["bind_dest"]).is_socket()
    assert (files["home_link"]).is_symlink()
    assert not (files["bind_dest"] / "bound_file.txt").is_symlink()
    assert (files["bind_dest"] / "bound_file.txt").exists()


def test_pathlib_info(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    assert files["path"].owner()
    assert files["path"].group()
    assert files["bind_dest"].owner()
    assert files["bind_dest"].group()


def test_pathlib_glob(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)

    result = [Path(f).name for f in files['path'].glob("*")]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result
    result = [Path(f).name for f in files['bind_dest'].glob("*")]
    assert "bound_file.txt" in result


def test_pathlib_rglob(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    str_activate_guard_files(rules)
    result = list(files['path'].rglob("*"))
    assert files["path"] / "ignore.log" not in result
    assert files["path"] / "visible.txt" in result
    assert files["bind_dest"] / "bound_file.txt" in result


def test_pathlib_iterdir(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    result = [f.name for f in Path(files['path']).iterdir()]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

    result = [f.name for f in Path(files['bind_dest']).iterdir()]
    assert "bound_file.txt" in result


def test_pathlib_chmod_and_lchmod(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    mode = files["path"].stat().st_mode
    assert files["path"].chmod(mode | stat.S_IREAD) is None
    assert (files["bind_dest"] / "bound_file.txt").chmod(
        mode | stat.S_IREAD) is None
    assert files["path"].lchmod(mode | stat.S_IREAD) is None
    assert (files["bind_dest"] / "bound_file.txt").lchmod(
        mode | stat.S_IREAD) is None


def test_pathlib_statand_stat_and_lstat(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)
    assert files['visible'].stat()
    with pytest.raises(RuleFileNotFoundError):
        assert files['ignore'].stat()
    assert files["home_link"].stat(follow_symlinks=True)
    assert (files['bind_dest'] / 'bound_file.txt').stat(follow_symlinks=True)

    assert files["home_link"].lstat()
    assert (files['bind_dest'] / 'bound_file.txt').lstat()


def test_pathlib_mkdir_removedirs_and_rmdir(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    (files["path"] / "dir_to_remove").mkdir()
    assert (files["path"] / "dir_to_remove").rmdir() is None

    (files["bind_dest"] / "dir_to_remove").mkdir()
    assert (files["bind_dest"] / "dir_to_remove").rmdir() is None

    # FIXME
    # (files["path"] / "dir_to_remove").mkdir()
    # assert os.removedirs(files["path"] / "dir_to_remove") is None
    #
    # os.mkdir(files["bind_dest"] / "dir_to_remove")
    # assert os.removedirs(files["bind_dest"] / "dir_to_remove") is None


def test_pathlib_link_symlink_and_readlink(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0)
    ]
    str_activate_guard_files(rules)

    assert files['home_link'].readlink() == files['visible']
    assert files['home_link_to_bind_src'].readlink() == files['bound_file']
    assert files['home_link_relative_to_bind_src'].readlink() == files['bound_file']
    assert (files['bind_dest'] / 'link_to_bind_src').readlink() == files['bound_file']
    assert (files["link_to_bind"]).readlink() == files['bound_file']
    assert (files["link_relative_to_bind"]).readlink() == files['bound_file']
    with pytest.raises(RuleFileNotFoundError):
        assert (files['home_link_to_ignore']).readlink()

    files['new_link'].hardlink_to(files['visible'])
    assert files['new_link'].exists()
    files['new_link'].unlink()

    files['new_link_to_bind'].hardlink_to(files['bound_file'])
    assert files['new_link_to_bind'].exists()
    files['new_link_to_bind'].unlink()

    with pytest.raises(RuleFileNotFoundError):
        (files["new_link"]).hardlink_to(files['bind_src'] / "toto")

    files['new_link'].symlink_to(files['visible'])
    assert files['new_link'].exists()
    assert files['new_link'].readlink() == files['visible']
    files['new_link'].unlink()

    files['new_link_to_bind'].symlink_to(files['bound_file'])
    assert files['new_link_to_bind'].exists()
    assert files['new_link_to_bind'].readlink() == files['bound_file']
    files['new_link_to_bind'].unlink()

    with pytest.raises(RuleFileNotFoundError):
        (files["new_link"]).symlink_to(files['bind_src'] / "toto")


def test_pathlib_link_symlink_and_readlink_refused(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    with pytest.raises(PermissionError):
        files['bound_file'].hardlink_to(files['visible'])


def test_pathlib_touch(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    assert files["path"].touch() is None
    assert (files["bind_dest"] / "bound_file.txt").touch() is None
    with pytest.raises(RuleFileNotFoundError):
        files["ignore"].touch()
    with pytest.raises(RuleFileNotFoundError):
        files["bind_src"].touch()


def test_pathlib_touch_refused(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    with pytest.raises(PermissionError):
        files["bound_file"].touch() is None


def test_pathlib_rename(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    files["to_rename"].write_text("To rename")
    assert (files["to_rename"]).rename(
        files["new_rename"]) == files["new_rename"]
    files["new_rename"].unlink()

    files["bind_to_rename"].write_text("To rename")
    assert files["bind_to_rename"].rename(files["new_bind_rename"]) == files[
        "new_bind_rename"]
    files["new_bind_rename"].unlink()

    with pytest.raises(RuleFileNotFoundError):
        files["ignore"].rename(files["ignore"])
    with pytest.raises(RuleFileNotFoundError):
        files["bind_src"].rename(files["bind_src"])


def test_pathlib_rename_refused(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    with pytest.raises(PermissionError):  # TODO: refuse in et out
        files["bound_file"].rename(files["bind_dest"] / "new_rename")


def test_pathlib_replace(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    files["to_replace"].write_text("To replace")
    files["to_replace"].replace(files["new_replace"])
    files["new_replace"].unlink()

    files["bind_to_replace"].write_text("To replace")
    files["bind_to_replace"].replace(files["new_bind_replace"])
    files["new_bind_replace"].unlink()

    with pytest.raises(RuleFileNotFoundError):
        files["ignore"].replace(files["new_replace"])

    with pytest.raises(RuleFileNotFoundError):
        files["bind_src"].replace(files["new_replace"])


def test_pathlib_replace_refused(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    with pytest.raises(PermissionError):  # TODO: refuse in et out
        files["bound_file"].replace(files["bind_dest"] / "new_replace")


def test_pathlib_resolve(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    assert (files["bind_dest"] / ".." / "visible.txt").resolve() == files["visible"]


def test_pathlib_samefile(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    assert (files["visible"]).samefile(files["visible"])
    assert (files["bound_file"]).samefile(files["bound_file"])
    with pytest.raises(RuleFileNotFoundError):
        assert (files["ignore"]).samefile(files["ignore"])


def test_pathlib_walk(files):
    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--ro-bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]
    str_activate_guard_files(rules)

    rc = list(files["path"].walk())
    assert rc[0][0] == files["path"]
    assert "bind_src" not in rc[0][1]
    assert "bind_dest" in rc[0][1]
    assert rc[1][0] == files["bind_dest"]
    assert "bound_file.txt" in rc[1][2]

    rc = list(files["bind_dest"].walk())
    assert rc[0][0] == files["bind_dest"]
    assert "bound_file.txt" in rc[0][2]
