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

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError, RulePermissionError, guard_files, sandbox_denials
from pysandboxes import learning as learning_mod
from pysandboxes.guard_files import (
    FSExposeRule,
    LearnFileRule,
    _apply_dest_to_src_rules,
    _apply_src_to_dest_rules,
    _check_is_in_rules,
    _dir_fd_path,
    _DirEntry,
    _ignore_matches,
    _is_unsafe_rule_path,
    _link_target,
    _wrap_buitins_open,
    _wrap_filename,
    _wrap_os_access,
    _wrap_os_chdir,
    _wrap_os_getcwd,
    _wrap_os_getcwdb,
    _wrap_os_listdir,
    _wrap_os_open,
    _wrap_os_path_realpath,
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
from pysandboxes.tools import follow_links_executable

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


def test_windows_disk_usage_calls_the_guarded_nt_function(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_files.sys, "platform", "win32")

    assert "nt._getdiskusage" in guard_files.patch_rules(learn=False)


# %% re-entrancy flags


def _seen_flag(variable: Any) -> tuple[Callable[..., str], list[bool]]:
    seen: list[bool] = []

    def probe(*args: Any, **kwargs: Any) -> str:
        seen.append(variable.get())
        return "probe"

    return probe, seen


def test_the_absolute_path_helper_flags_the_real_working_directory_while_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, seen = _seen_flag(guard_files._realpath_cwd)
    monkeypatch.setattr(guard_files, "_os_path_abspath_unguarded", probe)

    guard_files._os_path_abspath("x")

    assert seen == [True]
    assert guard_files._realpath_cwd.get() is False


def test_realpath_flags_the_real_working_directory_while_it_runs() -> None:
    probe, seen = _seen_flag(guard_files._realpath_cwd)

    guard_files._wrap_os_path_realpath(probe)("x")

    assert seen == [True]
    assert guard_files._realpath_cwd.get() is False


def test_the_canonical_helpers_flag_the_canonicalization_while_they_run(monkeypatch: pytest.MonkeyPatch) -> None:
    realpath, realpath_seen = _seen_flag(guard_files._canonicalizing)
    islink, islink_seen = _seen_flag(guard_files._canonicalizing)
    monkeypatch.setattr(guard_files, "_os_path_realpath", realpath)
    monkeypatch.setattr(guard_files.os.path, "islink", islink)

    guard_files._safe_realpath("x")
    guard_files._is_link("x")

    assert realpath_seen == [True]
    assert islink_seen == [True]
    assert guard_files._canonicalizing.get() is False


def test_getcwd_reports_the_remapped_directory_except_inside_realpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_files, "_apply_src_to_dest_rules", lambda path: ("/virtual/", None))
    wrapper = guard_files._wrap_os_getcwd(lambda: "/real")

    assert wrapper() == "/virtual"
    token = guard_files._realpath_cwd.set(True)
    try:
        assert wrapper() == "/real"
    finally:
        guard_files._realpath_cwd.reset(token)


# %% parse_rules


def test_parse_rules_rejects_a_path_that_is_a_file(tmp_path: Path) -> None:
    plain_file = tmp_path / "f.txt"
    plain_file.write_text("x")
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([ConfigLine(f"expose-ro={plain_file}", Path(), 0)], errors)

    assert len(errors) == 1
    assert "must be a directory" in errors[0][0]
    assert not any(isinstance(r, FSExposeRule) and r.config.rule.startswith("expose-") for r in file_rules)


@pytest.mark.parametrize("bad", ["file", "missing", "null-byte"])
def test_parse_rules_keeps_reading_the_rules_after_an_invalid_one(tmp_path: Path, bad: str) -> None:
    plain_file = tmp_path / "f.txt"
    plain_file.write_text("x")
    good = tmp_path / "good"
    good.mkdir()
    bad_path = {"file": str(plain_file), "missing": str(tmp_path / "nope"), "null-byte": "a\x00b"}[bad]
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules(
        [ConfigLine(f"expose-ro={bad_path}", Path(), 0), ConfigLine(f"expose-ro={good}", Path(), 1)], errors
    )

    assert len(errors) == 1
    assert str(good) + os.sep in [r.path for r in file_rules if isinstance(r, FSExposeRule)]


def test_generate_rules_skips_a_safe_device_without_dropping_the_other_paths(tmp_path: Path) -> None:
    dirs = []
    for index in range(40):
        directory = tmp_path / f"d{index}"
        directory.mkdir()
        dirs.append(directory)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(Path("/dev/null"), True), *(LearnFileRule(d, False) for d in dirs)})

    assert not any("/dev/null" in r for r in rules)
    assert sorted(rules) == sorted(f"expose-ro={d}" for d in dirs)


def test_parse_rules_rejects_a_path_with_an_embedded_null_byte() -> None:
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([ConfigLine("expose-ro=a\x00b", Path(), 0)], errors)

    assert len(errors) == 1
    # Windows resolves such a name without raising from Python 3.13, then finds no file by that name.
    windows_resolves = sys.platform == "win32" and sys.version_info >= (3, 13)
    assert ("must exist" if windows_resolves else "path is invalid") in errors[0][0]
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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows file names cannot contain a newline")
def test_generate_rules_skips_a_path_containing_a_newline(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """NA2: a directory name containing a newline -- valid on POSIX, and this is a real
    directory created on disk, not a crafted string -- must not be written unescaped into
    an ``expose-rw=`` line: reloaded line by line, it would become three directives
    (``expose-rw=.../evil``, a free-standing ``os-sandbox=none``, then a comment) instead
    of the single rule that was observed."""
    evil = tmp_path / "evil\nos-sandbox=none\n#"
    evil.mkdir()

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
        caplog.at_level(logging.WARNING, logger="pysandboxes.guard_files"),
    ):
        rules = generate_rules({LearnFileRule(evil, False)})

    assert rules == []
    assert any("cannot be safely re-encoded" in r.getMessage() for r in caplog.records)


def test_generate_rules_skips_a_path_containing_a_hash(tmp_path: Path) -> None:
    """A ``#`` with no newline still corrupts the line: ``tools._remove_comment`` treats it as
    an unquoted end-of-line comment marker and would truncate the rule to a shorter, different
    path than the one observed."""
    evil = tmp_path / "evil#dir"
    evil.mkdir()

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(evil, False)})

    assert rules == []


# %% _ignore_matches


def test_ignore_matches_strips_ntfs_stream_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")

    assert _ignore_matches("secret.txt::$DATA", "secret.txt") is True
    assert _ignore_matches("other.txt::$DATA", "secret.txt") is False


# %% _apply_ignore_rule / _apply_src_to_dest_rules / _apply_dest_to_src_rules


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


def test_wrap_os_getcwd_reports_a_directory_hidden_by_an_ignore_rule_without_opening_it(tmp_path: Path) -> None:
    """The name of the working directory is reported; what it holds stays hidden."""
    (tmp_path / "secret.txt").write_text("secret")
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    wrapped = _wrap_os_getcwd(lambda: str(tmp_path))

    assert wrapped() == str(tmp_path)
    with pytest.raises(RuleFileNotFoundError) as exc:
        open(tmp_path / "secret.txt")
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


def test_wrap_os_getcwdb_reports_a_directory_hidden_by_an_ignore_rule_without_opening_it(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("secret")
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    wrapped = _wrap_os_getcwdb(lambda: str(tmp_path).encode())

    assert wrapped() == str(tmp_path).encode()
    with pytest.raises(RuleFileNotFoundError) as exc:
        open(tmp_path / "secret.txt")
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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot os.open a directory")
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


# %% parse_rules -- the conflicting-duplicate-rule and interpreter-exposure branches


def test_parse_rules_flags_a_conflicting_duplicate_rule_regardless_of_order(tmp_path: Path) -> None:
    """`write != is_write` must not be loosened to an ordering comparison: the existing test only
    exercises the (ro, rw) order, which coincides with `<`/`<=` too."""
    errors: list[ErrorMsg] = []
    rules = [
        ConfigLine(f"expose-rw={tmp_path}", Path(), 0),
        ConfigLine(f"expose-ro={tmp_path}", Path(), 1),
    ]

    file_rules, _ = parse_rules(rules, errors)

    assert len(errors) == 1
    assert "invalidate another rule" in errors[0][0]


def test_parse_rules_allows_two_identical_duplicate_rules(tmp_path: Path) -> None:
    """Two identical `expose-ro=` lines for the same path (e.g. from an `include`) are a harmless
    duplicate, not a conflict: `<=` would wrongly flag the (False, False) pair `!=` does not."""
    errors: list[ErrorMsg] = []
    rules = [
        ConfigLine(f"expose-ro={tmp_path}", Path(), 0),
        ConfigLine(f"expose-ro={tmp_path}", Path(), 1),
    ]

    file_rules, _ = parse_rules(rules, errors)

    assert errors == []


def test_parse_rules_always_exposes_the_python_interpreter() -> None:
    """Without the `for p in list_bin` loop, no expose rule for the interpreter is ever emitted,
    breaking the sandboxed Python's own ability to start."""
    if not follow_links_executable(Path(sys.executable), set()):
        pytest.skip("this interpreter's chain resolves straight into /usr/bin: nothing is recorded")
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([], errors)

    assert any(isinstance(r, FSExposeRule) and r.config.rule == "<python>" for r in file_rules)


def test_parse_rules_exposes_both_a_pythons_link_name_and_its_resolved_name() -> None:
    """The interpreter chain may reach through a link whose resolved target differs (e.g. a uv
    venv reaching `cpython-3.13-...` through a link to `cpython-3.13.7-...`); both names need
    their own rule, or the sandboxed process -- which reports the link name -- is denied."""
    list_bin = follow_links_executable(Path(sys.executable), set())
    link_and_target = next(
        ((p, p.resolve()) for p in list_bin if p != p.resolve()),
        None,
    )
    if link_and_target is None:
        pytest.skip("the interpreter here is not reached through a symlink with a different resolved name")
    link, target = link_and_target

    errors: list[ErrorMsg] = []
    file_rules, _ = parse_rules([], errors)

    python_paths = {
        r.path.rstrip(os.sep) for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule == "<python>"
    }
    assert str(link) in python_paths
    assert str(target) in python_paths


def test_parse_rules_marks_a_directory_interpreter_path_with_a_trailing_separator() -> None:
    """A directory reached through the interpreter chain (e.g. a venv root) must store a rule
    ending in the native separator, or a sibling directory sharing the same string prefix
    (`.venv` vs `.venv-evil`) would also match it."""
    errors: list[ErrorMsg] = []
    file_rules, _ = parse_rules([], errors)

    python_rules = [r for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule == "<python>"]
    directory_rules = [r for r in python_rules if Path(r.path.rstrip(os.sep)).is_dir()]
    if not directory_rules:
        pytest.skip("this interpreter's chain never adds a directory (e.g. no venv root in it)")
    assert all(r.path.endswith(os.sep) for r in directory_rules)


def test_parse_rules_exposes_the_standard_library_read_only_when_it_is_apart_from_the_interpreter(
    tmp_path: Path,
) -> None:
    """A system interpreter (`/usr/bin/python3`) is not under its standard library (`/usr/lib/python3.12`): without
    its own rule, `zipfile` cannot read `encodings.cp437` and lib-dynload stays out of reach."""
    stdlib = tmp_path / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    errors: list[ErrorMsg] = []

    with patch.object(os, "__file__", str(stdlib / "os.py")):
        file_rules, _ = parse_rules([], errors)

    rules = [r for r in file_rules if isinstance(r, FSExposeRule) and r.path == str(stdlib.resolve()) + os.sep]
    assert [(r.write, r.config.rule) for r in rules] == [(False, "<python>")]


# %% _check_is_in_rules


def test_check_is_in_rules_does_not_match_a_path_merely_sorting_before_a_rule(tmp_path: Path) -> None:
    """`spath == rule.path` must not accept a path that only sorts earlier, such as the parent of
    the exposed directory: that parent is not itself covered by the rule."""
    rule = FSExposeRule(path=str(tmp_path) + os.sep, write=True, config=ConfigLine("x", Path(), 0))
    activate_guard((rule,))

    assert _check_is_in_rules(tmp_path.parent) is False


# %% _is_unsafe_rule_path


def test_is_unsafe_rule_path_flags_leading_and_trailing_whitespace(tmp_path: Path) -> None:
    leading = tmp_path / " padded"
    trailing = tmp_path / "padded "

    assert _is_unsafe_rule_path(leading) is True
    assert _is_unsafe_rule_path(trailing) is True


# %% generate_rules -- /proc, interpreter exclusion, overflow de-duplication


def test_generate_rules_skips_only_proc_paths_not_every_path_after_it(tmp_path: Path) -> None:
    """`continue` must skip only the `/proc` entry; `break` would also discard every learned path
    the input carries after it."""
    work = tmp_path / "project"
    work.mkdir()
    ordered_learn = [LearnFileRule(Path("/proc/stat"), False), LearnFileRule(work, False)]

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules(ordered_learn)  # type: ignore[arg-type]

    assert rules == [f"expose-ro={work}"]


def test_generate_rules_skips_a_path_inside_the_interpreters_own_tree() -> None:
    """A learned path inside the interpreter/venv tree is already covered by `parse_rules`'s own
    python-bin rule: recording it again would be a redundant duplicate."""
    if not follow_links_executable(Path(sys.executable), set()):
        pytest.skip("this interpreter's chain resolves straight into /usr/bin: list_bin is empty")
    candidate = Path(sys.executable).resolve().parent / "some_stdlib_file.py"

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(candidate, False)})

    assert rules == []


def test_generate_rules_skips_only_the_unsafe_path_not_every_path_after_it(tmp_path: Path) -> None:
    """`continue` must skip only the unsafe path; `break` would also discard every safe path
    sorted after it."""
    bad = tmp_path / "bad#dir"
    good = tmp_path / "zzz_good_dir"
    bad.mkdir()
    good.mkdir()
    assert str(bad) < str(good)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(bad, False), LearnFileRule(good, False)})

    assert rules == [f"expose-ro={good}"]


def test_generate_rules_skips_a_non_regular_file(tmp_path: Path) -> None:
    """A learned path that exists but is neither a file nor a directory (e.g. a FIFO) must not
    get a rule: `exists() and (is_file() or is_dir()) and access(R_OK)` guards that."""
    if sys.platform == "win32":
        pytest.skip("no FIFOs on Windows")
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        # A path under the fifo does not exist either, so it collapses to the fifo itself --
        # the same way a plain file's path collapses to its (directory) parent.
        rules = generate_rules({LearnFileRule(fifo / "child", False)})

    assert rules == []


def test_generate_rules_deduplicates_a_path_sorting_before_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`allready_path == home` (and the symmetric `path != home`) are always False by
    construction; an ordering comparison must not spuriously match an entry that merely sorts
    before `home` and skip (or lose) its overflow de-duplication."""
    fake_home = tmp_path / "zzz_home"
    fake_home.mkdir()
    parent = tmp_path / "aaa_parent"
    child = parent / "sub"
    child.mkdir(parents=True)
    assert str(parent) < str(fake_home)

    monkeypatch.setattr("pysandboxes.guard_files.Path.home", staticmethod(lambda: fake_home))

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(parent, False), LearnFileRule(child, False)})

    assert rules == [f"expose-ro={parent}"]


@pytest.mark.parametrize("allready_write, write", [(True, False), (False, True)])
def test_generate_rules_keeps_a_nested_paths_own_rule_when_write_mode_differs(
    tmp_path: Path, allready_write: bool, write: bool
) -> None:
    """A nested path whose write mode differs from its already-recorded ancestor is not an
    overflow: `==` must not be replaced by an ordering comparison that only agrees for one of
    the two (True, False) orderings."""
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(parent, allready_write), LearnFileRule(child, write)})

    expected = sorted(
        {
            f"{'expose-rw' if allready_write else 'expose-ro'}={parent}",
            f"{'expose-rw' if write else 'expose-ro'}={child}",
        }
    )
    assert rules == expected


def test_generate_rules_processes_paths_after_an_overflowing_one(tmp_path: Path) -> None:
    """An overflowing (redundant) path must only skip itself: `break` instead of `continue` would
    also discard every path sorted after it."""
    parent = tmp_path / "aaa_parent"
    child = parent / "sub"
    other = tmp_path / "zzz_other"
    child.mkdir(parents=True)
    other.mkdir()

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(parent, False), LearnFileRule(child, False), LearnFileRule(other, False)})

    assert rules == sorted([f"expose-ro={parent}", f"expose-ro={other}"])


def test_generate_rules_does_not_blank_a_special_var_relative_path_starting_below_dot(tmp_path: Path) -> None:
    """Only the exact match (`x == "/."`) collapses to the whole special directory: a child whose
    name sorts below `.` (ASCII), such as one starting with `!`, must keep its narrow subpath."""
    work = tmp_path / "work"
    work.mkdir()
    child = work / "!weird"
    child.mkdir()

    with (
        patch.dict("pysandboxes.guard_files._special_env", {"PWD": str(work)}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(child, False)})

    assert rules == ["expose-ro=./!weird"]


def test_generate_rules_keeps_the_longest_special_home_match(tmp_path: Path) -> None:
    """`_special_home` is sorted longest-value-first precisely so the first match wins: `break`
    must stop there, not let a shorter, less specific entry overwrite it."""
    venv = tmp_path / "venv"
    nested = venv / "nested"
    nested.mkdir(parents=True)

    with (
        patch.dict(
            "pysandboxes.guard_files._special_home",
            {"VIRTUAL_ENV": str(venv), "CONDA_HOME": str(tmp_path)},
            clear=True,
        ),
        # Cleared so the `for-else` can never fall into the `_special_env` branch and mask a
        # `continue` that lets the loop run to completion without ever reaching `break`.
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(nested, False)})

    assert rules == ["expose-ro=${VIRTUAL_ENV}"]


def test_generate_rules_keeps_the_longest_special_env_match(tmp_path: Path) -> None:
    """`_special_env` is sorted longest-value-first precisely so the first match wins: `break`
    must stop there, not let a shorter, less specific entry overwrite it."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    target = inner / "work"
    target.mkdir()

    with (
        patch.dict(
            "pysandboxes.guard_files._special_env",
            {"PWD": str(inner), "TMPDIR": str(outer)},
            clear=True,
        ),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({LearnFileRule(target, False)})

    assert rules == ["expose-ro=./work"]


# %% _wrap_os_open -- flags handling


def test_wrap_os_open_decodes_a_bytes_path_for_an_exposed_file(tmp_path: Path) -> None:
    """A real bytes path must be fsdecode'd before being matched against the (string) rules."""
    target = tmp_path / "f.txt"
    target.write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_open(os.open)

    fd = wrapped(str(target).encode(), os.O_RDONLY)
    os.close(fd)


@pytest.mark.skipif(os.open not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_wrap_os_open_allows_a_readonly_open_through_a_read_only_dir_fd(tmp_path: Path) -> None:
    """`isinstance(flags, int)` must not be loosened: `os.open`'s real `flags` is always an int,
    and treating it as if it were not would force every dir_fd open to need write access."""
    (tmp_path / "f.txt").write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_open(os.open)
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        fd = wrapped("f.txt", os.O_RDONLY, dir_fd=dir_fd)
        os.close(fd)
    finally:
        os.close(dir_fd)


# %% _wrap_os_listdir / _wrap_os_readlink / _wrap_os_rmdir -- bytes decoding


def test_wrap_os_listdir_decodes_a_bytes_path_for_an_exposed_directory(tmp_path: Path) -> None:
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_listdir(os.listdir)

    assert wrapped(str(tmp_path).encode()) == os.listdir(tmp_path)


def test_wrap_os_readlink_decodes_a_bytes_path_for_an_exposed_link(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(target)
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_readlink(os.readlink)

    assert wrapped(str(link).encode()) == str(target)


def test_wrap_os_rmdir_decodes_a_bytes_path_for_an_exposed_directory(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    activate_guard_files_rules([ConfigLine(f"expose-rw={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_rmdir(os.rmdir)

    wrapped(str(sub).encode())

    assert not sub.exists()


# %% _wrap_os_readlink -- learning records a read, not a write


def test_wrap_os_readlink_learns_an_unexposed_link_as_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(target)
    wrapped = _wrap_os_readlink(os.readlink)
    monkeypatch.setattr(learning_mod, "_learning", set())

    with patch.object(guard_files, "_rules", ()):
        set_learning_mode(True)
        try:
            wrapped(str(link))
        finally:
            set_learning_mode(False)

    assert LearnFileRule(Path(str(link)), False) in learning_mod._learning


def test_wrap_os_readlink_learns_an_unexposed_target_as_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("x")
    inside = tmp_path / "inside"
    inside.mkdir()
    link = inside / "link"
    link.symlink_to(target)
    activate_guard_files_rules([ConfigLine(f"expose-ro={inside}", Path(), 0)])
    wrapped = _wrap_os_readlink(os.readlink)
    monkeypatch.setattr(learning_mod, "_learning", set())

    set_learning_mode(True)
    try:
        wrapped(str(link))
    finally:
        set_learning_mode(False)

    assert LearnFileRule(target, False) in learning_mod._learning


# %% _wrap_os_symlink -- plain-path write protection


def test_wrap_os_symlink_denies_a_read_only_destination_without_dir_fd(tmp_path: Path) -> None:
    """Creating a symlink in a read-only exposed directory must be denied on the main, non-dir_fd
    code path too, not only through a dir_fd."""
    target = tmp_path / "target.txt"
    target.write_text("x")
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_symlink(os.symlink)

    with pytest.raises(RulePermissionError):
        wrapped(str(target), str(tmp_path / "link"))

    assert not (tmp_path / "link").exists()


# %% _body_two_filenames -- dst_dir_fd must be checked through _check_dir_fd


@pytest.mark.skipif(os.rename not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_body_two_filenames_checks_the_destination_dir_fd_even_with_a_plain_source(tmp_path: Path) -> None:
    """`dst_dir_fd` must be resolved through `_check_dir_fd`, not treated as a plain CWD-relative
    path once given -- escaping the directory the descriptor actually names."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    (src_dir / "source.txt").write_text("hi")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={src_dir}", Path(), 0),
            ConfigLine(f"expose-ro={dst_dir}", Path(), 1),
        ]
    )
    wrapped = _wrap_two_filenames(os.rename, in_write=True, out_write=True)
    dst_dir_fd = os.open(str(dst_dir), os.O_RDONLY)
    try:
        with pytest.raises(RulePermissionError):
            wrapped(str(src_dir / "source.txt"), "target.txt", dst_dir_fd=dst_dir_fd)
    finally:
        os.close(dst_dir_fd)
    assert not (dst_dir / "target.txt").exists()


# %% _wrap_os_getcwd -- root edge case


def test_wrap_os_getcwd_keeps_the_root_separator() -> None:
    """At the filesystem root, the trailing separator must stay: stripping it would return ''
    instead of '/'."""
    root = Path(os.getcwd()).anchor
    wrapped = _wrap_os_getcwd(lambda: root)

    assert wrapped() == root


def test_wrap_os_path_realpath_lets_the_standard_library_ask_for_the_working_directory(tmp_path: Path) -> None:
    """``ntpath.realpath`` asks for the working directory before Python 3.13, which no rule exposes: it is reported."""
    activate_guard_files_rules([ConfigLine(f"ignore={tmp_path}{os.sep}", Path(), 0)])
    getcwd = _wrap_os_getcwd(lambda: str(tmp_path))
    asked: list[str] = []

    def realpath(path: str) -> str:
        asked.append(getcwd())
        return path

    assert _wrap_os_path_realpath(realpath)("x") == "x"
    assert asked == [str(tmp_path)]
    assert getcwd() == str(tmp_path)


# %% _link_target -- Windows extended-length prefix


def test_link_target_drops_the_extended_length_prefix_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")

    assert _link_target("\\\\?\\C:\\data\\file") == "C:\\data\\file"
    assert _link_target("C:\\data\\file") == "C:\\data\\file"


def test_link_target_keeps_a_name_starting_like_the_prefix_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")

    assert _link_target("\\\\?\\name") == "\\\\?\\name"


# %% _wrap_os_readlink -- dir_fd learning write flag


@pytest.mark.skipif(os.readlink not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_wrap_os_readlink_reads_a_link_through_dir_fd_in_a_read_only_directory(tmp_path: Path) -> None:
    """The directory holding a link read through a `dir_fd` is only checked for read access, not
    write."""
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(target)
    activate_guard_files_rules([ConfigLine(f"expose-ro={tmp_path}", Path(), 0)])
    wrapped = _wrap_os_readlink(os.readlink)
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        result = wrapped("link", dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    assert Path(result) == target


# %% _check_dir_fd_entry -- learning records the actual write intent


@pytest.mark.skipif(os.unlink not in os.supports_dir_fd, reason="no dir_fd on this platform")
def test_wrap_os_unlink_records_a_dir_fd_removal_as_a_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The permission check for a dir_fd unlink is hard-coded elsewhere; only the learning-mode
    record depends on the `write` flag `_wrap_os_unlink` passes to `_check_dir_fd_entry`."""
    (tmp_path / "f.txt").write_text("x")
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    wrapped = _wrap_os_unlink(os.unlink)
    monkeypatch.setattr(learning_mod, "_learning", set())
    try:
        with patch.object(guard_files, "_rules", ()):
            set_learning_mode(True)
            try:
                wrapped("f.txt", dir_fd=dir_fd)
            finally:
                set_learning_mode(False)
    finally:
        os.close(dir_fd)

    assert LearnFileRule(Path(str(tmp_path / "f.txt")), True) in learning_mod._learning


@pytest.mark.skipif(not hasattr(os, "O_TMPFILE"), reason="O_TMPFILE is Linux only")
def test_opening_a_directory_is_a_read_but_an_unnamed_temporary_file_is_a_write() -> None:
    assert not guard_files._opens_for_write(os.O_RDONLY | os.O_DIRECTORY)
    assert guard_files._opens_for_write(os.O_TMPFILE | os.O_RDWR)
    assert guard_files._opens_for_write(os.O_RDONLY | os.O_TRUNC)
    assert not guard_files._opens_for_write(os.O_RDONLY)
