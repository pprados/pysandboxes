# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`guard_files`: the contextvar scopes, the parsing of `expose-*` lines and the default rules it adds."""

import os
from pathlib import Path
from typing import Any, Iterator, cast
from unittest.mock import MagicMock

import pytest

from pysandboxes import guard_files
from pysandboxes.guard_files import FSExposeRule, parse_rules
from pysandboxes.sb_types import ConfigLine


def _parse(*lines: str) -> tuple[list[FSExposeRule], list[Any]]:
    errors: list[Any] = []
    rules, _ = parse_rules([ConfigLine(line, Path(), 0) for line in lines], errors)
    return [rule for rule in rules if isinstance(rule, FSExposeRule)], errors


def _paths(rules: list[FSExposeRule]) -> list[str]:
    return [rule.path for rule in rules]


def test_a_relative_path_is_resolved_against_the_real_working_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def abspath(path: str) -> str:
        seen.append(guard_files._realpath_cwd.get())
        return path

    monkeypatch.setattr(guard_files, "_os_path_abspath_unguarded", abspath)

    guard_files._os_path_abspath("relative")

    assert seen == [True]
    assert guard_files._realpath_cwd.get() is False


def test_the_link_test_does_not_re_enter_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def islink(path: str) -> bool:
        seen.append(guard_files._canonicalizing.get())
        return False

    monkeypatch.setattr(os.path, "islink", islink)

    assert guard_files._is_link("/anything") is False

    assert seen == [True]
    assert guard_files._canonicalizing.get() is False


def test_an_invalid_path_does_not_hide_the_rules_that_follow_it(tmp_path: Path) -> None:
    rules, errors = _parse("expose-ro=/tmp/a\0b", f"expose-ro={tmp_path}")

    assert [error[0] for error in errors if "path is invalid" in error[0]]
    assert guard_files._dir_path(str(tmp_path.resolve())) in _paths(rules)


def test_a_file_where_a_directory_is_required_does_not_hide_the_rules_that_follow_it(tmp_path: Path) -> None:
    plain_file = tmp_path / "plain"
    plain_file.write_text("")
    exposed = tmp_path / "exposed"
    exposed.mkdir()

    rules, errors = _parse(f"expose-ro={plain_file}", f"expose-ro={exposed}")

    assert [error[0] for error in errors if "must be a directory" in error[0]]
    assert guard_files._dir_path(str(exposed.resolve())) in _paths(rules)


class TestDefaultStandardLibraryRule:
    @pytest.fixture
    def fake_stdlib(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        """A standard library the interpreter chain does not already cover."""
        stdlib = (tmp_path / "stdlib").resolve()
        stdlib.mkdir()
        monkeypatch.setattr(os, "__file__", str(stdlib / "os.py"))
        monkeypatch.setattr(guard_files, "follow_links_executable", lambda *args: iter(()))
        return guard_files._dir_path(str(stdlib))

    def test_it_is_added_whatever_the_rules_already_there_sort_after_it(self, fake_stdlib: str) -> None:
        rules, _ = _parse("expose-ro=/usr")

        assert fake_stdlib in _paths(rules)

    def test_it_is_not_added_twice(self, fake_stdlib: str) -> None:
        rules, _ = _parse(f"expose-ro={fake_stdlib}")

        assert _paths(rules).count(fake_stdlib) == 1


class _Ordered(list[Any]):
    """A learned set that is walked in the order it was given."""

    def copy(self) -> "_Ordered":
        return self


def _generate(monkeypatch: pytest.MonkeyPatch, *learned: Path, home: str = "/zzz-home", write: bool = False) -> Any:
    monkeypatch.setattr(guard_files, "_special_home", {})
    monkeypatch.setattr(guard_files, "_special_env", {})
    monkeypatch.setattr(guard_files._learn_env, "_original_envs", {"HOME": home})
    ordered = _Ordered(guard_files.LearnFileRule(path, write) for path in learned)
    return guard_files.generate_rules(cast(set[Any], ordered))


class TestGenerateRules:
    def test_a_device_the_profile_does_not_know_is_learned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _generate(monkeypatch, Path("/dev/full")) == ["expose-ro=/dev/full"]

    def test_a_safe_device_does_not_hide_the_paths_learned_after_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert _generate(monkeypatch, Path("/dev/null"), tmp_path) == [f"expose-ro={tmp_path}"]

    def test_a_directory_inside_a_learned_one_with_the_same_access_adds_no_rule(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "inner").mkdir()

        assert _generate(monkeypatch, tmp_path, tmp_path / "inner") == [f"expose-ro={tmp_path}"]

    def test_the_home_directory_never_covers_what_is_learned_inside_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "inner").mkdir()

        rules = _generate(monkeypatch, tmp_path, tmp_path / "inner", home=str(tmp_path))

        assert rules == sorted([f"expose-ro={tmp_path}", f"expose-ro={tmp_path / 'inner'}"])


def _expose(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Make ``tmp_path`` the only readable directory."""
    root = tmp_path.resolve()
    rule = FSExposeRule(path=guard_files._dir_path(str(root)), write=False, config=ConfigLine("test", Path(), 0))
    monkeypatch.setattr(guard_files, "_rules", (rule,))
    return root


@pytest.fixture
def exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _expose(monkeypatch, tmp_path)


class TestDirectoryDescriptors:
    def test_the_proc_probe_is_remembered_once_it_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        probes: list[str] = []
        monkeypatch.setattr(guard_files, "_proc_fd_usable", None)
        monkeypatch.setattr(guard_files, "_os_stat", lambda path: probes.append(path))

        assert guard_files._proc_fd_available() is True
        assert guard_files._proc_fd_usable is True
        assert guard_files._proc_fd_available() is True
        assert probes == ["/proc/self/fd"]

    def test_a_failed_proc_probe_is_remembered_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(path: str) -> None:
            raise OSError(path)

        monkeypatch.setattr(guard_files, "_proc_fd_usable", None)
        monkeypatch.setattr(guard_files, "_os_stat", refuse)

        assert guard_files._proc_fd_available() is False
        assert guard_files._proc_fd_usable is False

    def test_a_descriptor_reused_for_another_inode_is_not_trusted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fd = os.open(tmp_path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            monkeypatch.setattr(guard_files, "_tracked_dir_fds", {fd: (st.st_dev, st.st_ino, "/recorded")})
            assert guard_files._tracked_dir_fd_path(fd) == "/recorded"

            monkeypatch.setattr(guard_files, "_tracked_dir_fds", {fd: (st.st_dev, st.st_ino + 1, "/recorded")})
            assert guard_files._tracked_dir_fd_path(fd) is None
        finally:
            os.close(fd)

    @pytest.mark.parametrize(
        ("platform", "proc", "recorded"),
        [("linux", False, True), ("linux", True, False), ("darwin", False, False), ("win32", False, False)],
    )
    def test_a_directory_is_recorded_only_on_linux_without_proc(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, proc: bool, recorded: bool
    ) -> None:
        tracked: dict[int, tuple[int, int, str]] = {}
        monkeypatch.setattr(guard_files, "_tracked_dir_fds", tracked)
        monkeypatch.setattr(guard_files, "_proc_fd_available", lambda: proc)
        monkeypatch.setattr(guard_files.sys, "platform", platform)
        fd = os.open(tmp_path, os.O_RDONLY)
        try:
            assert guard_files._remember_dir_fd(fd, str(tmp_path), None) == fd
        finally:
            os.close(fd)

        assert bool(tracked) is recorded

    def test_a_platform_other_than_macos_reads_the_directory_through_proc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard_files.sys, "platform", "aix")
        monkeypatch.setattr(guard_files, "_proc_fd_available", lambda: True)
        monkeypatch.setattr(guard_files, "_os_readlink", lambda path: "/the/directory")

        assert guard_files._dir_fd_path("name", 5) == "/the/directory/name"


class TestOpenFlags:
    def test_an_unnamed_temporary_file_is_a_write(self) -> None:
        assert guard_files._opens_for_write(os.O_TMPFILE | os.O_RDWR) is True
        assert guard_files._opens_for_write(os.O_TMPFILE) is True

    def test_opening_a_directory_is_a_read(self) -> None:
        assert guard_files._opens_for_write(os.O_RDONLY | os.O_DIRECTORY) is False

    def test_without_o_tmpfile_a_read_stays_a_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delattr(os, "O_TMPFILE", raising=False)

        assert guard_files._opens_for_write(os.O_RDONLY) is False
        assert guard_files._opens_for_write(os.O_WRONLY) is True


class TestWorkingDirectory:
    def test_the_directory_a_realpath_asks_for_is_returned_as_the_system_gives_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wrapper = guard_files._wrap_os_getcwd(lambda: "/some/dir/")
        token = guard_files._realpath_cwd.set(True)
        try:
            assert wrapper() == "/some/dir/"
        finally:
            guard_files._realpath_cwd.reset(token)

        assert wrapper() == "/some/dir"

    def test_a_realpath_runs_with_the_working_directory_allowed(self) -> None:
        seen: list[bool] = []
        wrapper = guard_files._wrap_os_path_realpath(
            lambda *args, **kwargs: seen.append(guard_files._realpath_cwd.get())
        )

        wrapper("/x")

        assert seen == [True]
        assert guard_files._realpath_cwd.get() is False


class TestReadingPaths:
    def test_a_bytes_path_is_decoded_before_the_rules_judge_it(self, exposed: Path) -> None:
        access = guard_files._wrap_os_access(os.access, write=False)

        assert access(os.fsencode(exposed), os.R_OK) is True

    def test_a_relative_link_target_is_read_from_the_directory_holding_the_link(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "target").write_text("")
        (tmp_path / "link").symlink_to("target")
        root = _expose(monkeypatch, tmp_path)
        readlink = guard_files._wrap_os_readlink(os.readlink)
        fd = os.open(root, os.O_RDONLY)
        try:
            assert readlink("link", dir_fd=fd) == str(root / "target")
        finally:
            os.close(fd)


class TestScanDirContext:
    def _context(self, scanner: Any) -> Any:
        context = object.__new__(guard_files._ScanDirContextManager)
        context.scanner = scanner
        return context

    def test_the_scanner_is_closed_with_the_context(self) -> None:
        scanner = MagicMock()

        self._context(scanner).close()

        scanner.close.assert_called_once_with()

    @pytest.mark.parametrize("scanner", [None, object()])
    def test_nothing_is_closed_without_a_closable_scanner(self, scanner: Any) -> None:
        self._context(scanner).close()


class TestPlatformRules:
    @pytest.mark.parametrize(
        ("platform", "bsd_flags", "owner"),
        [
            ("linux", False, True),
            ("win32", False, False),
            ("darwin", True, True),
            ("freebsd14", True, True),
            ("zzz", True, True),
        ],
    )
    def test_each_platform_gets_the_rules_of_the_calls_it_has(
        self, monkeypatch: pytest.MonkeyPatch, platform: str, bsd_flags: bool, owner: bool
    ) -> None:
        monkeypatch.setattr(guard_files.sys, "platform", platform)

        rules = guard_files.patch_rules(learn=False)

        assert ("os.chflags" in rules) is bsd_flags
        assert ("os.chown" in rules) is owner

    @pytest.mark.parametrize(("version", "rule"), [((3, 12, 5, "final", 0), True), ((3, 14, 0, "final", 0), False)])
    def test_windows_before_python_3_13_resolves_real_paths_through_the_guard(
        self, monkeypatch: pytest.MonkeyPatch, version: tuple[Any, ...], rule: bool
    ) -> None:
        monkeypatch.setattr(guard_files.sys, "platform", "win32")
        monkeypatch.setattr(guard_files.sys, "version_info", version)

        assert ("os.path.realpath" in guard_files.patch_rules(learn=False)) is rule

    def test_the_windows_disk_usage_call_only_needs_read_access(
        self, monkeypatch: pytest.MonkeyPatch, exposed: Path
    ) -> None:
        monkeypatch.setattr(guard_files.sys, "platform", "win32")

        wrapped = guard_files.patch_rules(learn=False)["nt._getdiskusage"](lambda path: "usage")

        assert wrapped(str(exposed)) == "usage"

    @pytest.mark.parametrize(("platform", "twin"), [("win32", {}), ("zzz", {"posix.open": "factory"})])
    def test_the_twin_module_is_nt_on_windows_and_posix_elsewhere(
        self, monkeypatch: pytest.MonkeyPatch, platform: str, twin: dict[str, str]
    ) -> None:
        monkeypatch.setattr(guard_files.sys, "platform", platform)

        assert guard_files._twin_rules({"os.open": "factory"}) == twin  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("platform", "stripped"), [("win32", True), ("zzz", False), ("linux", False), ("darwin", False)]
)
def test_the_windows_long_path_prefix_is_dropped_from_a_link_target_on_windows_only(
    monkeypatch: pytest.MonkeyPatch, platform: str, stripped: bool
) -> None:
    monkeypatch.setattr(guard_files.sys, "platform", platform)

    target = "\\\\?\\C:\\data"

    assert guard_files._link_target(target) == ("C:\\data" if stripped else target)


@pytest.mark.parametrize(
    ("platform", "name", "pattern", "matches"),
    [
        ("win32", "file.txt::$DATA", "file.txt", True),
        ("zzz", "file:stream", "file:stream", True),
        ("darwin", "SECRET", "secret", True),
        ("linux", "SECRET", "secret", False),
    ],
)
def test_an_ignore_pattern_follows_the_name_rules_of_the_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, name: str, pattern: str, matches: bool
) -> None:
    monkeypatch.setattr(guard_files.sys, "platform", platform)

    assert guard_files._ignore_matches(name, pattern) is matches


@pytest.mark.parametrize(("platform", "rule"), [("win32", True), ("zzz", False), ("darwin", False)])
def test_the_disk_usage_rule_exists_on_windows_only(monkeypatch: pytest.MonkeyPatch, platform: str, rule: bool) -> None:
    monkeypatch.setattr(guard_files.sys, "platform", platform)

    assert ("nt._getdiskusage" in guard_files.patch_rules(learn=False)) is rule


@pytest.mark.parametrize(
    ("version", "options"),
    [
        ((3, 11, 9, "final", 0), set()),
        ((3, 12, 0, "final", 0), {"case_sensitive"}),
        ((3, 13, 0, "final", 0), {"case_sensitive", "recurse_symlinks"}),
        ((3, 14, 0, "final", 0), {"case_sensitive", "recurse_symlinks"}),
    ],
)
def test_a_glob_passes_only_the_options_the_python_version_knows(
    monkeypatch: pytest.MonkeyPatch, exposed: Path, version: tuple[Any, ...], options: set[str]
) -> None:
    seen: list[set[str]] = []

    def native_glob(path: Path, pattern: str, **kwargs: Any) -> Iterator[Path]:
        seen.append(set(kwargs))
        return iter(())

    glob = guard_files._wrap_pathlib_Path_glob(native_glob)
    monkeypatch.setattr(guard_files.sys, "version_info", version)

    glob(exposed, "*")

    assert seen == [options]


@pytest.mark.parametrize("platform", ["aix", "android"])
def test_an_ignore_pattern_is_case_sensitive_off_windows_and_macos(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(guard_files.sys, "platform", platform)

    assert guard_files._ignore_matches("SECRET", "secret") is False


def test_a_safe_device_the_profile_already_exposes_is_not_added_twice() -> None:
    rules, _ = _parse("expose-ro=/dev/null")

    assert _paths(rules).count("/dev/null") == 1
