import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, RulePermissionError, sandbox_denials
from pysandboxes.guard_files import _check_alias, _wrap_shutil_copytree
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no os.chown")
def test_shutil_chown(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import shutil

    uid = os.stat(files["bind_dest"]).st_uid
    gid = os.stat(files["bind_dest"]).st_gid

    shutil.chown(files["bind_dest"], uid, gid)

    # files["path"] is exposed read-only: shutil.chown delegates to the guarded os.chown
    with pytest.raises(RulePermissionError):
        shutil.chown(files["visible"], uid, gid)


def test_shutil_copy(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.copy(files["visible"], files["new_replace"])
    assert files["new_replace"].read_text() == "Visible"
    files["new_replace"].unlink()
    shutil.copy(files["bound_file"], files["new_replace"])
    assert files["new_replace"].read_text() == "Content"
    files["new_replace"].unlink()


def test_shutil_copy2(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import pathlib
    import shutil

    shutil.copy2(files["visible"], files["new_replace"])
    files["new_replace"].unlink()
    shutil.copy2(files["bound_file"], files["new_replace"])
    files["new_replace"].unlink()
    out = files["bind_dest"] / "copy.txt"
    assert shutil.copy2(files["bound_file"], out) is out
    pathlib.Path(out).unlink()


def test_shutil_copyfile(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    shutil.copyfile(files["visible"], files["new_rename"])
    assert files["new_rename"].exists()
    files["new_rename"].unlink()

    import pathlib

    shutil.copyfile(files["bound_file"], files["bind_to_replace"])
    assert pathlib.Path(files["bind_to_replace"]).exists()
    pathlib.Path(files["bind_to_replace"]).unlink()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows chmod only toggles the read-only flag")
def test_shutil_copymode(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    files["visible"].chmod(0o640)
    files["bound_file"].chmod(0o600)
    activate_guard_files_rules(rules)

    import shutil

    shutil.copymode(files["visible"], files["bound_file"])
    assert files["bound_file"].stat().st_mode & 0o777 == 0o640
    shutil.copymode(files["bound_file"], files["bound_file"])


def test_shutil_copystat(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    os.utime(files["visible"], ns=(1_000_000_000, 1_000_000_000))
    activate_guard_files_rules(rules)

    import shutil

    shutil.copystat(files["visible"], files["bound_file"])
    assert files["bound_file"].stat().st_mtime_ns == 1_000_000_000
    os.utime(files["bound_file"], ns=(2_000_000_000, 2_000_000_000))
    shutil.copystat(files["bound_file"], files["visible"])
    assert files["visible"].stat().st_mtime_ns == 2_000_000_000


def test_shutil_copytree_and_move(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    if (files["path"] / "tmp").exists():
        shutil.rmtree(files["path"] / "tmp")
    if (files["path"] / "tmp2").exists():
        shutil.rmtree(files["path"] / "tmp2")
    shutil.copytree(files["bind_src"], files["path"] / "tmp")
    assert (files["path"] / "tmp" / "bound_file.txt").read_text() == "Content"
    shutil.move(files["path"] / "tmp", files["path"] / "tmp2")
    assert not (files["path"] / "tmp").exists()
    assert (files["path"] / "tmp2" / "bound_file.txt").read_text() == "Content"
    shutil.rmtree(files["path"] / "tmp2")
    assert not (files["path"] / "tmp2").exists()


def test_shutil_copytree_outside_the_rules_is_denied(
    files: Dict[str, Path],  # noqa: F811
) -> None:
    """A destination no rule exposes must be refused."""
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    with pytest.raises(RuleFileNotFoundError):
        shutil.copytree(files["bind_src"], files["bind_dest"] / "copied")


@pytest.mark.parametrize("dirs_exist_ok", [False, True])
def test_shutil_copytree_into_a_read_only_destination_is_denied(tmp_path: Path, dirs_exist_ok: bool) -> None:
    """The destination of a copy is written: a readable source must not make it writable.

    The walk runs with the alias checks off, so the check made before it is the only guard.
    """
    root = Path(os.path.realpath(tmp_path))
    source, destination = root / "rw", root / "ro"
    source.mkdir()
    destination.mkdir()
    (source / "f.txt").write_text("x")
    activate_guard_files_rules(
        [ConfigLine(f"expose-ro={destination}", Path(), 0), ConfigLine(f"expose-rw={source}", Path(), 0)]
    )

    import shutil

    target = destination if dirs_exist_ok else destination / "new"
    with pytest.raises(RulePermissionError):
        shutil.copytree(source, target, dirs_exist_ok=dirs_exist_ok)
    assert list(destination.iterdir()) == []


def test_shutil_disk_usage(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-ro={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    assert shutil.disk_usage(files["bind_dest"]).total > 0


def test_shutil_make_archive(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    archive = shutil.make_archive(
        base_name=str(files["path"] / "arch"),
        format="zip",
        root_dir=files["bind_dest"],  # dossier à compressor
    )
    with zipfile.ZipFile(archive) as zf:
        assert zf.read("bound_file.txt") == b"Content"


def test_shutil_rmtree(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    d = files["path"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    extra: dict[str, Any] = {}
    if sys.version_info[:2] > (3, 11):
        extra = {"onexc": None, "dir_fd": None}
    shutil.rmtree(d, ignore_errors=False, onerror=None, **extra)
    assert not d.exists()

    d = files["bind_dest"] / "dir_to_remove"
    d.mkdir()
    (d / "inner").mkdir()
    shutil.rmtree(d, ignore_errors=False, onerror=None, **extra)
    assert not d.exists()


def test_shutil_rmtree_cannot_empty_a_read_only_tree(files: Dict[str, Path]) -> None:  # noqa: F811
    """rmtree opens the tree for reading, then unlinks through ``dir_fd``: that must count as a write."""
    import shutil
    import tempfile

    tree = files["path"] / "ro_tree"
    (tree / "inner").mkdir(parents=True)
    (tree / "inner" / "f.txt").write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={files['path']}", Path(), 0)])

    assert shutil._use_fd_functions or sys.platform == "win32"  # type: ignore[attr-defined]
    with pytest.raises(RulePermissionError) as caught:
        shutil.rmtree(tree)
    # rmtree sets ``filename`` on the error: the denial must still name the rule. Only from 3.12,
    # where rmtree's fd-safe walk (not used on Windows) re-raises a per-entry failure through its own outer handler;
    # the pre-3.12 implementation never sets it.
    if sys.version_info >= (3, 12) and sys.platform != "win32":
        assert caught.value.filename is not None
    assert [repr(f"expose-ro={files['path']}")[1:-1] in d for d in sandbox_denials(caught.value)] == [True]
    assert (tree / "inner" / "f.txt").exists()

    activate_guard_files_rules([ConfigLine(f"expose-rw={files['path']}", Path(), 0)])
    with tempfile.TemporaryDirectory(dir=files["path"]) as scratch:
        (Path(scratch) / "inner").mkdir()
        (Path(scratch) / "inner" / "f.txt").write_text("x")
    assert not Path(scratch).exists()
    shutil.rmtree(tree)


def test_shutil_move(files: Dict[str, Path]) -> None:  # noqa: F811
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    s = files["path"] / "dir_to_move"
    d = files["path"] / "dir_moved"
    if s.exists():
        shutil.rmtree(s)
    if d.exists():
        shutil.rmtree(d)

    s.mkdir()
    (s / "inner").mkdir()
    shutil.move(s, d, copy_function=shutil.copy2)
    assert not s.exists()
    assert (d / "inner").is_dir()


def test_shutil_copytree_wraps_the_copy_function_restoring_alias_checks(files: Dict[str, Path]) -> None:  # noqa: F811
    """`copy_function` must be wrapped like `ignore`: the walk disables `_check_alias`, and the
    user callback needs it restored to stat paths safely."""
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import shutil

    seen_alias_states = []

    def spy_copy(src: str, dst: str, **kwargs: Any) -> Any:
        seen_alias_states.append(_check_alias.get())
        return shutil.copy2(src, dst, **kwargs)

    dest = files["path"] / "copied_with_spy"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(files["bind_src"], dest, copy_function=spy_copy)

    assert seen_alias_states and all(seen_alias_states)


def test_shutil_copytree_disables_alias_checks_for_its_own_duration(tmp_path: Path) -> None:
    """The walk itself must run with `_check_alias` off; only a user callback gets it restored."""
    recorded: list[bool] = []

    def fake_copytree(src: str, dst: str) -> str:
        recorded.append(_check_alias.get())
        return dst

    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    wrapped = _wrap_shutil_copytree(fake_copytree)

    wrapped(str(tmp_path / "a"), str(tmp_path / "b"))

    assert recorded == [False]


def test_shutil_copytree_reads_the_source_without_requiring_write_access(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("x")
    dest_parent = tmp_path / "dest_parent"
    dest_parent.mkdir()
    activate_guard_files_rules(
        [ConfigLine(f"expose-ro={src}", Path(), 0), ConfigLine(f"expose-rw={dest_parent}", Path(), 0)]
    )

    import shutil

    shutil.copytree(src, dest_parent / "copied")

    assert (dest_parent / "copied" / "f.txt").read_text() == "x"


def test_shutil_copytree_of_a_top_level_symlink_copies_by_its_target_not_its_holder(tmp_path: Path) -> None:
    """The top-level `src` must be judged on its resolved target (`_apply_dest_to_src_rules`),
    not on the directory holding the link (`_apply_rules_to_entry`'s move semantics)."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "f.txt").write_text("x")
    unexposed_holder = tmp_path / "unexposed_holder"
    unexposed_holder.mkdir()
    link = unexposed_holder / "link_to_real"
    link.symlink_to(real_dir, target_is_directory=True)
    dest_parent = tmp_path / "dest_parent"
    dest_parent.mkdir()
    activate_guard_files_rules(
        [ConfigLine(f"expose-ro={real_dir}", Path(), 0), ConfigLine(f"expose-rw={dest_parent}", Path(), 0)]
    )

    import shutil

    shutil.copytree(link, dest_parent / "copied")

    assert (dest_parent / "copied" / "f.txt").read_text() == "x"


def test_the_guarded_os_functions_keep_their_supports_sets(files: Dict[str, Path]) -> None:  # noqa: F811
    """A patched os function must stay in the os.supports_* sets its original was in.

    The standard library tests membership by identity -- shutil.copystat picks a
    no-op instead of os.stat when os.stat is missing from supports_follow_symlinks,
    and then fails on None.st_mode.
    """
    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    import os
    import shutil

    assert os.stat in os.supports_follow_symlinks
    assert os.stat in os.supports_fd
    if sys.platform != "win32":  # Windows supports no dir_fd at all: the set is empty
        assert os.stat in os.supports_dir_fd

    src = files["path"] / "tree_with_link"
    dst = files["path"] / "tree_with_link_copy"
    for tree in (src, dst):
        if tree.exists():
            shutil.rmtree(tree)
    src.mkdir()
    (src / "target.txt").write_text("content")
    (src / "link").symlink_to("target.txt")

    shutil.copytree(src, dst, symlinks=True)

    assert (dst / "link").is_symlink()
    assert (dst / "link").read_text() == "content"
    shutil.copy2(src / "link", dst / "link_copy", follow_symlinks=False)
    assert (dst / "link_copy").is_symlink()


def test_patching_os_environ_leaves_the_supports_sets_alone() -> None:
    """Learning mode patches os.environ too, and a _Environ cannot be hashed."""
    import os

    from pysandboxes.guard_import import _keep_os_supports_sets

    before = {name: set(getattr(os, name)) for name in ("supports_follow_symlinks", "supports_fd")}

    _keep_os_supports_sets(os.environ, os.environ)

    assert {name: set(getattr(os, name)) for name in before} == before


def test_patching_os_functions_replaces_originals_in_supports_sets() -> None:
    import os

    from pysandboxes.guard_import import _OS_SUPPORTS_SETS, _keep_os_supports_sets

    def original() -> None:
        pass

    def patched() -> None:
        pass

    before = {name: set(getattr(os, name)) for name in _OS_SUPPORTS_SETS if hasattr(os, name)}
    try:
        for supports in before:
            getattr(os, supports).add(original)

        _keep_os_supports_sets(original, patched)

        for name in before:
            supports_set = getattr(os, name)
            assert original not in supports_set
            assert patched in supports_set
    finally:
        for name, members in before.items():
            supports_set = getattr(os, name)
            supports_set.clear()
            supports_set.update(members)


def test_patching_os_functions_only_touches_supports_sets_that_held_the_original() -> None:
    """A function absent from a given ``os.supports_*`` set must stay absent after patching it.

    ``getattr(os, set_name, None)`` is never ``None`` in practice, so an ``or`` in place of the
    ``and`` would unconditionally add ``patched`` to every set, not just the ones ``original``
    actually belonged to.
    """
    import os

    from pysandboxes.guard_import import _OS_SUPPORTS_SETS, _keep_os_supports_sets

    def original() -> None:
        pass

    def patched() -> None:
        pass

    before = {name: set(getattr(os, name)) for name in _OS_SUPPORTS_SETS if hasattr(os, name)}
    try:
        for supports in before:
            getattr(os, supports).discard(original)  # None of them hold it

        _keep_os_supports_sets(original, patched)

        for name in before:
            supports_set = getattr(os, name)
            assert patched not in supports_set
    finally:
        for name, members in before.items():
            supports_set = getattr(os, name)
            supports_set.clear()
            supports_set.update(members)
