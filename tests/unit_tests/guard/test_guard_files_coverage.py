# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Coverage for `guard_files` branches the rest of the suite never reaches.

Each test either calls a low-level helper directly or builds a wrapper with
`_wrap_*` and a fake or an underlying function -- the same technique already
used by `test_guard_escape_fixes.py` -- so a rule can be armed without a full
sandbox activation. The "underlying function" passed to a `_wrap_*` factory is
often `os.unlink` or similar: under this suite's conftest, that name is already
the guarded version installed by `activate_guard_import`, so the call goes
through the wrapper twice. Both layers see the same armed `_rules`, so the
branch a test targets is exercised either way. A refusal is asserted through
`sandbox_denials()`, one named exception type, and
(where relevant) that the file system was left untouched -- checked with the
rules disarmed first, since a post-condition check goes through the very
guard the test just armed, and a hidden file reads as absent to `exists()`.
"""

import os
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, RulePermissionError, guard_files, sandbox_denials
from pysandboxes import learning as learning_mod
from pysandboxes.guard_files import (
    FSExposeRule,
    IgnoreRule,
    LearnFileRule,
    _apply_dest_to_src_rules,
    _apply_ignore_rule,
    _apply_src_to_dest_rules,
    _check_is_in_rules,
    _dir_fd_path,
    _DirEntry,
    _ignore_matches,
    _wrap_buitins_open,
    _wrap_filename,
    _wrap_os_access,
    _wrap_os_chdir,
    _wrap_os_getcwd,
    _wrap_os_getcwdb,
    _wrap_os_listdir,
    _wrap_os_open,
    _wrap_os_readlink,
    _wrap_os_rmdir,
    _wrap_os_stat,
    _wrap_os_symlink,
    _wrap_os_unlink,
    _wrap_two_filenames,
    activate_guard,
    generate_rules,
    parse_rules,
)
from pysandboxes.learning import set_learning_mode
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import _deactivate_all_rules, activate_guard_files_rules

# %% _DirEntry


def test_dir_entry_setattr_delegates_to_the_wrapped_target() -> None:
    """`__fspath__`/`__str__` are the only things `_DirEntry` owns; anything set on it must land
    on the real `os.DirEntry` it wraps, or a caller mutating it would silently write nowhere."""

    class _Dummy:
        pass

    target = _Dummy()
    entry = _DirEntry(target, "/some/path")

    entry.custom_attr = "value"  # type: ignore[attr-defined]

    assert target.custom_attr == "value"  # type: ignore[attr-defined]


# %% parse_rules


def test_parse_rules_rejects_a_path_that_is_a_file(tmp_path: Path) -> None:
    plain_file = tmp_path / "f.txt"
    plain_file.write_text("x")
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([ConfigLine(f"expose-ro={plain_file}", Path(), 0)], errors)

    assert len(errors) == 1
    assert "must be a directory" in errors[0][0]
    assert not any(isinstance(r, FSExposeRule) and r.config.rule.startswith("expose-") for r in file_rules)


def test_parse_rules_rejects_a_path_with_an_embedded_null_byte() -> None:
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([ConfigLine("expose-ro=a\x00b", Path(), 0)], errors)

    assert len(errors) == 1
    assert "path is invalid" in errors[0][0]
    assert not any(isinstance(r, FSExposeRule) and r.config.rule.startswith("expose-") for r in file_rules)


def test_parse_rules_flags_a_conflicting_duplicate_rule(tmp_path: Path) -> None:
    """The same directory named once read-only and once read-write is a configuration error;
    the first rule wins and only one `FSExposeRule` is kept for that path."""
    errors: list[ErrorMsg] = []
    rules = [
        ConfigLine(f"expose-ro={tmp_path}", Path(), 0),
        ConfigLine(f"expose-rw={tmp_path}", Path(), 1),
    ]

    file_rules, _ = parse_rules(rules, errors)

    assert len(errors) == 1
    assert "invalidate another rule" in errors[0][0]
    expose_rules = [r for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule.startswith("expose-")]
    assert len(expose_rules) == 1
    assert expose_rules[0].write is False


# %% _check_is_in_rules


def test_check_is_in_rules_finds_a_matching_expose_rule(tmp_path: Path) -> None:
    rule = FSExposeRule(path=str(tmp_path) + os.sep, write=True, config=ConfigLine("x", Path(), 0))
    activate_guard((rule,))

    assert _check_is_in_rules(tmp_path) is True


# %% generate_rules


def test_generate_rules_collapses_a_learned_subpath_of_a_special_home_dir(tmp_path: Path) -> None:
    """Unlike the `_special_env` branch just below it, this one drops the relative suffix and
    substitutes the whole special directory -- reported to the maintainer as worth confirming,
    not fixed here: it may be the intended, coarser exposure for a cache root such as HF_HOME."""
    venv = tmp_path / "venv"
    project = venv / "project"
    project.mkdir(parents=True)

    with patch.dict("pysandboxes.guard_files._special_home", {"VIRTUAL_ENV": str(venv)}, clear=True):
        rules = generate_rules({LearnFileRule(project, False)})

    assert any(r.startswith("expose-ro=${VIRTUAL_ENV}") for r in rules)


def test_generate_rules_collapses_a_learned_path_matching_pwd_exactly(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()

    with (
        patch.dict("pysandboxes.guard_files._special_env", {"PWD": str(work)}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(work, False)})

    assert "expose-ro=." in rules


def test_generate_rules_skips_a_path_already_covered_by_a_broader_rule(tmp_path: Path) -> None:
    """A sub-directory of an already emitted rule, with the same write mode, adds nothing new."""
    parent = tmp_path / "proj"
    child = parent / "sub"
    child.mkdir(parents=True)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(parent, False), LearnFileRule(child, False)})

    assert rules == [f"expose-ro={parent}"]


@pytest.mark.parametrize("path", ["/proc/stat", "/proc/sys/kernel/random/uuid", "/proc/self/status"])
def test_generate_rules_writes_nothing_under_proc(path: str) -> None:
    """psutil reads /proc/stat at import: widened to its directory, the rule would expose every
    process's environ and cmdline."""
    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(Path(path), False)})

    assert rules == []


# %% _ignore_matches


def test_ignore_matches_strips_ntfs_stream_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")

    assert _ignore_matches("secret.txt::$DATA", "secret.txt") is True
    assert _ignore_matches("other.txt::$DATA", "secret.txt") is False


# %% _apply_ignore_rule / _apply_src_to_dest_rules / _apply_dest_to_src_rules


def test_apply_ignore_rule_matches_by_name(tmp_path: Path) -> None:
    rule = IgnoreRule("secret.*", ConfigLine("ignore=secret.*", Path(), 0))

    with patch.object(guard_files, "_rules", (rule,)):
        result = _apply_ignore_rule(str(tmp_path / "secret.txt"))

    assert result == (None, rule)


def test_apply_src_to_dest_rules_rejects_an_unknown_rule_type(tmp_path: Path) -> None:
    bogus = object()

    with patch.object(guard_files, "_rules", (bogus,)):
        with pytest.raises(AssertionError):
            _apply_src_to_dest_rules(str(tmp_path / "f.txt"))


def test_apply_dest_to_src_rules_rejects_an_unknown_rule_type(tmp_path: Path) -> None:
    bogus = object()

    with patch.object(guard_files, "_rules", (bogus,)):
        with pytest.raises(AssertionError):
            _apply_dest_to_src_rules(str(tmp_path / "f.txt"), write=False)


def test_apply_dest_to_src_rules_skips_a_rule_without_a_path(tmp_path: Path) -> None:
    bogus = FSExposeRule(path=None, write=True, config=ConfigLine("x", Path(), 0))  # type: ignore[arg-type]

    with patch.object(guard_files, "_rules", (bogus,)):
        assert _apply_dest_to_src_rules(str(tmp_path / "f.txt"), write=False) == (None, None)


def test_apply_dest_to_src_rules_learns_a_write_upgrade_instead_of_denying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    rule = FSExposeRule(path=str(tmp_path) + os.sep, write=False, config=ConfigLine(f"expose-ro={tmp_path}", Path(), 0))
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", (rule,)):
        set_learning_mode(True)
        try:
            remapped, hit_rule = _apply_dest_to_src_rules(str(target), write=True)
        finally:
            set_learning_mode(False)

    assert remapped == str(target)
    assert hit_rule is None
    assert LearnFileRule(Path(str(target)), True) in learning_mod._learning


# %% _wrap_os_stat


def test_wrap_os_stat_passes_through_a_file_descriptor() -> None:
    calls: list[object] = []

    def fake_stat(path: object, dir_fd: object, follow_symlinks: object) -> str:
        calls.append(path)
        return "stat-result"

    wrapped = _wrap_os_stat(fake_stat, write=False)

    result = wrapped(5, dir_fd=None, follow_symlinks=True)

    assert result == "stat-result"
    assert calls == [5]


def test_wrap_os_stat_decodes_a_bytes_path(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    calls: list[object] = []

    def fake_stat(path: object, dir_fd: object, follow_symlinks: object) -> str:
        calls.append(path)
        return "ok"

    wrapped = _wrap_os_stat(fake_stat, write=False)

    result = wrapped(str(target).encode(), dir_fd=None, follow_symlinks=True)

    assert result == "ok"
    assert calls == [str(target)]


def test_wrap_os_stat_falls_through_during_learning_without_recording(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    calls: list[object] = []

    def fake_stat(path: object, dir_fd: object, follow_symlinks: object) -> str:
        calls.append(path)
        return "stat-result"

    wrapped = _wrap_os_stat(fake_stat, write=False)

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            result = wrapped(str(target), dir_fd=None, follow_symlinks=True)
        finally:
            set_learning_mode(False)

    assert result == "stat-result"
    assert calls == [str(target)]


# %% _wrap_os_chdir


def test_wrap_os_chdir_passes_through_a_file_descriptor() -> None:
    calls: list[object] = []
    wrapped = _wrap_os_chdir(lambda path: calls.append(path), write=False)

    wrapped(5)

    assert calls == [5]


def test_wrap_os_chdir_decodes_a_bytes_path(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    calls: list[Path] = []
    wrapped = _wrap_os_chdir(lambda path: calls.append(Path(path)), write=False)

    wrapped(str(tmp_path).encode())

    assert calls == [tmp_path]


def test_wrap_os_chdir_learns_an_unexposed_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    calls: list[object] = []
    wrapped = _wrap_os_chdir(lambda path: calls.append(path), write=False)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(target))
        finally:
            set_learning_mode(False)

    assert calls == [str(target)]
    assert LearnFileRule(Path(str(target)), False) in learning_mod._learning


# %% _wrap_os_access


def test_wrap_os_access_passes_through_a_file_descriptor() -> None:
    calls: list[dict[str, object]] = []

    def fake_access(**kw: object) -> bool:
        calls.append(kw)
        return True

    wrapped = _wrap_os_access(fake_access, write=False)

    assert wrapped(5, os.F_OK) is True
    assert calls[0]["path"] == 5


def test_wrap_os_access_reports_an_ignored_path_as_inaccessible(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("x")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=secret.txt", Path(), 1),
        ]
    )
    wrapped = _wrap_os_access(os.access, write=False)

    assert wrapped(str(target).encode(), os.F_OK) is False


def test_wrap_os_access_forwards_the_real_check_during_learning(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    wrapped = _wrap_os_access(os.access, write=False)

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            result = wrapped(str(target), os.F_OK)
        finally:
            set_learning_mode(False)

    assert result is True


# %% _wrap_os_getcwd / _wrap_os_getcwdb


def test_wrap_os_getcwd_denies_a_directory_hidden_by_an_ignore_rule(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    wrapped = _wrap_os_getcwd(lambda: str(tmp_path))

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped()

    assert sandbox_denials(exc.value)


def test_wrap_os_getcwd_learns_a_directory_hidden_by_an_ignore_rule(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    wrapped = _wrap_os_getcwd(lambda: str(tmp_path))

    set_learning_mode(True)
    try:
        result = wrapped()
    finally:
        set_learning_mode(False)

    assert result == str(tmp_path)


def test_wrap_os_getcwdb_denies_a_directory_hidden_by_an_ignore_rule(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    wrapped = _wrap_os_getcwdb(lambda: str(tmp_path).encode())

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped()

    assert sandbox_denials(exc.value)


# %% _wrap_os_listdir


def test_wrap_os_listdir_passes_through_a_file_descriptor() -> None:
    calls: list[object] = []

    def fake_listdir(path: object = None) -> list[str]:
        calls.append(path)
        return ["a"]

    wrapped = _wrap_os_listdir(fake_listdir)

    assert wrapped(5) == ["a"]
    assert calls == [5]


def test_wrap_os_listdir_denies_a_directory_matched_by_an_ignore_rule(tmp_path: Path) -> None:
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine(f"ignore={tmp_path.name}", Path(), 1),
        ]
    )
    wrapped = _wrap_os_listdir(os.listdir)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(tmp_path).encode())

    assert sandbox_denials(exc.value)


# %% _wrap_os_readlink


def test_wrap_os_readlink_learns_an_unexposed_link(tmp_path: Path) -> None:
    link = tmp_path / "link"
    target = tmp_path / "target.txt"
    target.write_text("x")
    link.symlink_to(target)
    wrapped = _wrap_os_readlink(os.readlink)

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            result = wrapped(str(link))
        finally:
            set_learning_mode(False)

    assert Path(result) == target


# %% builtins.open / _wrap_filename / _wrap_two_filenames


def test_wrap_buitins_open_learns_an_unexposed_file_then_opens_it(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("data")
    wrapped = _wrap_buitins_open(open)

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            with wrapped(str(target)) as f:
                content = f.read()
        finally:
            set_learning_mode(False)

    assert content == "data"


def test_wrap_filename_passes_through_a_file_descriptor() -> None:
    calls: list[object] = []

    def fake_filename(file: object, *a: object, **k: object) -> str:
        calls.append(file)
        return "ok"

    wrapped = _wrap_filename(fake_filename, write=False)

    assert wrapped(7) == "ok"
    assert calls == [7]


def test_wrap_filename_learns_an_unexposed_bytes_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "x.txt"
    wrapped = _wrap_filename(lambda file: "ok", write=True, learn=True)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            result = wrapped(str(target).encode())
        finally:
            set_learning_mode(False)

    assert result == "ok"
    assert LearnFileRule(Path(str(target)), True) in learning_mod._learning


def test_body_two_filenames_decodes_bytes_paths_for_both_sides(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("hi")
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)

    wrapped(str(src).encode(), str(dest).encode())

    assert dest.read_text() == "hi"
    assert not src.exists()


def test_body_two_filenames_denies_an_ignored_destination(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("hi")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=dest.txt", Path(), 1),
        ]
    )
    wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(src), str(tmp_path / "dest.txt"))

    assert sandbox_denials(exc.value)
    assert src.exists()


@pytest.mark.skipif(os.rename not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_body_two_filenames_denies_rename_through_a_read_only_dir_fd(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("source")
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
        wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)
        with pytest.raises(RulePermissionError):
            wrapped("source.txt", "target.txt", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    assert (tmp_path / "source.txt").read_text() == "source"
    assert not (tmp_path / "target.txt").exists()


def test_body_two_filenames_learns_unexposed_src_and_dest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("hi")
    wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(src), str(dest))
        finally:
            set_learning_mode(False)

    assert dest.read_text() == "hi"
    assert LearnFileRule(Path(str(src)), True) in learning_mod._learning
    assert LearnFileRule(Path(str(dest)), True) in learning_mod._learning


def test_body_two_filenames_denies_an_unexposed_source(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)

    with patch.object(guard_files, "_rules", ()):
        with pytest.raises(RuleFileNotFoundError) as exc:
            wrapped(str(src), str(tmp_path / "dest.txt"))

    assert sandbox_denials(exc.value)


# %% _wrap_os_open


def test_wrap_os_open_passes_through_a_file_descriptor() -> None:
    calls: list[dict[str, object]] = []

    def fake_open(**kw: object) -> int:
        calls.append(kw)
        return 42

    wrapped = _wrap_os_open(fake_open)

    assert wrapped(9, os.O_RDONLY) == 42
    assert calls[0]["path"] == 9


def test_wrap_os_open_denies_an_ignored_path_with_dir_fd(tmp_path: Path) -> None:
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=secret.txt", Path(), 1),
        ]
    )
    wrapped = _wrap_os_open(os.open)
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        with pytest.raises(RuleFileNotFoundError) as exc:
            wrapped("secret.txt", os.O_RDONLY, dir_fd=dir_fd)
        assert sandbox_denials(exc.value)
    finally:
        os.close(dir_fd)


@pytest.mark.skipif(os.open not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_wrap_os_open_denies_a_write_through_a_read_only_dir_fd(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("keep")
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
        wrapped = _wrap_os_open(os.open)
        with pytest.raises(RulePermissionError):
            wrapped(target.name, os.O_WRONLY | os.O_TRUNC, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    assert target.read_text() == "keep"


def test_wrap_os_open_learns_the_actual_write_intent_of_an_unexposed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "new.txt"
    wrapped = _wrap_os_open(os.open)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            fd = wrapped(str(target), os.O_WRONLY | os.O_CREAT)
            os.close(fd)
        finally:
            set_learning_mode(False)

    assert LearnFileRule(Path(str(target)), True) in learning_mod._learning


# %% _wrap_os_symlink


def test_wrap_os_symlink_passes_through_file_descriptors() -> None:
    calls: list[dict[str, object]] = []

    def fake_symlink(**kw: object) -> str:
        calls.append(kw)
        return "ok"

    wrapped = _wrap_os_symlink(fake_symlink)

    assert wrapped(3, 4) == "ok"
    assert calls == [{"src": 3, "dst": 4, "target_is_directory": False, "dir_fd": None}]


def test_wrap_os_symlink_decodes_bytes_paths(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link"
    wrapped = _wrap_os_symlink(os.symlink)

    wrapped(str(target).encode(), str(link).encode())

    assert link.is_symlink()


def test_wrap_os_symlink_denies_an_ignored_destination(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=link", Path(), 1),
        ]
    )
    wrapped = _wrap_os_symlink(os.symlink)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(target), str(tmp_path / "link"))

    assert sandbox_denials(exc.value)


@pytest.mark.skipif(os.symlink not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_wrap_os_symlink_denies_a_read_only_dir_fd(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
        wrapped = _wrap_os_symlink(os.symlink)
        with pytest.raises(RulePermissionError):
            wrapped(target.name, "link", dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    assert not (tmp_path / "link").exists()


def test_wrap_os_symlink_denies_an_ignored_target(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=target.txt", Path(), 1),
        ]
    )
    wrapped = _wrap_os_symlink(os.symlink)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(target), str(tmp_path / "link"))

    assert sandbox_denials(exc.value)


def test_wrap_os_symlink_learns_an_unexposed_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("x")
    inside = tmp_path / "inside"
    inside.mkdir()
    link = inside / "link"
    activate_guard_files_rules([ConfigLine(f"expose-rw={inside}", Path(), 0)])
    wrapped = _wrap_os_symlink(os.symlink)
    monkeypatch.setattr(learning_mod, "_learning", set())

    set_learning_mode(True)
    try:
        wrapped(str(target), str(link))
    finally:
        set_learning_mode(False)

    assert LearnFileRule(Path(str(target)), False) in learning_mod._learning
    # The link resolves outside the exposed directory, so a guarded `lstat` denies it too
    # (the same escape `test_guard_escape_fixes.py` pins): disarm before checking.
    _deactivate_all_rules()
    assert link.is_symlink()


def test_wrap_os_symlink_learns_the_write_intent_of_an_unexposed_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link"
    wrapped = _wrap_os_symlink(os.symlink)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(target), str(link))
        finally:
            set_learning_mode(False)

    assert LearnFileRule(Path(str(link)), True) in learning_mod._learning


# %% _wrap_os_unlink / _wrap_os_rmdir


def test_wrap_os_unlink_denies_an_ignored_file(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("x")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=secret.txt", Path(), 1),
        ]
    )
    wrapped = _wrap_os_unlink(os.unlink)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(target).encode())

    assert sandbox_denials(exc.value)
    # The ignore rule also hides the file from a guarded `stat`, so `exists()` would
    # read it as absent even though it survived: disarm before checking.
    _deactivate_all_rules()
    assert target.exists()


def test_wrap_os_unlink_learns_an_unexposed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    wrapped = _wrap_os_unlink(os.unlink)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(target))
        finally:
            set_learning_mode(False)

    assert not target.exists()
    assert LearnFileRule(Path(str(target)), True) in learning_mod._learning


def test_wrap_os_unlink_is_blocked_by_a_read_only_rule(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_unlink(os.unlink)

    with pytest.raises(RulePermissionError):
        wrapped(str(target))

    assert target.exists()


def test_wrap_os_rmdir_denies_an_ignored_directory(tmp_path: Path) -> None:
    sub = tmp_path / "secretdir"
    sub.mkdir()
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
            ConfigLine("ignore=secretdir", Path(), 1),
        ]
    )
    wrapped = _wrap_os_rmdir(os.rmdir)

    with pytest.raises(RuleFileNotFoundError) as exc:
        wrapped(str(sub).encode())

    assert sandbox_denials(exc.value)
    # The ignore rule also hides the directory from a guarded `stat`, so `exists()` would
    # read it as absent even though it survived: disarm before checking.
    _deactivate_all_rules()
    assert sub.exists()


def test_wrap_os_rmdir_learns_an_unexposed_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    wrapped = _wrap_os_rmdir(os.rmdir)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(sub))
        finally:
            set_learning_mode(False)

    assert not sub.exists()
    assert LearnFileRule(Path(str(sub)), True) in learning_mod._learning


def test_wrap_os_rmdir_is_blocked_by_a_read_only_rule(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_rmdir(os.rmdir)

    with pytest.raises(RulePermissionError):
        wrapped(str(sub))

    assert sub.exists()


@pytest.mark.skipif(os.unlink not in os.supports_dir_fd, reason="no dir_fd on this platform")
@pytest.mark.parametrize("wrap, func, name", [(_wrap_os_unlink, os.unlink, "f.txt"), (_wrap_os_rmdir, os.rmdir, "sub")])
def test_a_dir_fd_removal_is_checked_against_the_directory_it_names(
    tmp_path: Path, wrap: Callable[..., Any], func: Callable[..., Any], name: str
) -> None:
    """A relative name under ``dir_fd`` resolves in that directory, so expose-ro holds there too."""
    (tmp_path / "f.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    wrapped = wrap(func)
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
        with pytest.raises(RulePermissionError):
            wrapped(name, dir_fd=dir_fd)
        assert (tmp_path / name).exists()

        activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
        wrapped(name, dir_fd=dir_fd)
        assert not (tmp_path / name).exists()
    finally:
        os.close(dir_fd)


def test_dir_fd_path_denies_a_descriptor_it_cannot_resolve() -> None:
    with pytest.raises(RuleFileNotFoundError):
        _dir_fd_path("f.txt", 987654)


def test_every_tool_directory_variable_is_recognised(tmp_path: Path) -> None:
    """Each variable of the list names its own directory: a missing comma joined two of them into one name."""
    import subprocess
    import sys

    names = ["TRANSFORMERS_CACHE", "TORCH_HOME", "KERAS_HOME"]
    env = {**os.environ, **{name: str(tmp_path / name.lower()) for name in names}}
    done = subprocess.run(
        [sys.executable, "-c", "from pysandboxes import guard_files; print(*sorted(guard_files._special_home))"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert set(names) <= set(done.stdout.split())
