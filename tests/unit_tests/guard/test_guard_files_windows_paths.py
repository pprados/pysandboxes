# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The file guard compares Windows paths in their own separator.

On a Windows runner the armed guard refused the working directory itself, as
'D:\\a\\pysandboxes\\pysandboxes/': a '/' glued to a native path never prefixes a
rule stored as 'D:\\...\\'. Windows is simulated here with ``ntpath``, on any host.
The simulation is scoped to a ``with`` block and every assertion runs after it:
pytest itself goes through the guard, and must not see Windows semantics.
"""

import ntpath
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

import pytest

from pysandboxes import guard_files
from pysandboxes.guard_files import FilesRule, FSExposeRule, IgnoreRule
from pysandboxes.sb_types import ConfigLine

_CONFIG = ConfigLine("test", Path(), 0)


@contextmanager
def _windows(rules: tuple[FilesRule, ...] | None = None) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(guard_files.os, "sep", "\\")
        mp.setattr(guard_files.os.path, "isabs", ntpath.isabs)
        mp.setattr(guard_files, "_os_path_abspath", ntpath.normpath)
        mp.setattr(guard_files, "_os_path_realpath", ntpath.normpath)
        # A relative ignore pattern is matched against the name, which Windows splits on '\\'.
        mp.setattr(guard_files, "Path", PureWindowsPath)
        if rules is not None:
            mp.setattr(guard_files, "_rules", rules)
        yield


def test_the_dir_form_of_a_windows_path_ends_with_a_backslash() -> None:
    with _windows():
        dir_forms = [guard_files._dir_path(p) for p in ("D:\\a\\repo", "D:\\")]
    assert dir_forms == ["D:\\a\\repo\\", "D:\\"]


def test_an_exposed_windows_directory_accepts_itself_and_its_content() -> None:
    accepted = ("D:\\a\\repo", "D:\\a\\repo\\", "D:\\a\\repo\\src\\x.py")
    with _windows((FSExposeRule("D:\\a\\repo\\", False, _CONFIG),)):
        results = [guard_files._apply_dest_to_src_rules(guard_files._dir_path(p), write=False) for p in accepted]
        outside = guard_files._apply_dest_to_src_rules("D:\\a\\other\\", write=False)
    assert all(remapped is not None and rule is None for remapped, rule in results), results
    assert outside == (None, None)


def test_an_absolute_windows_ignore_rule_matches_the_full_path() -> None:
    ignore = IgnoreRule("D:\\a\\repo\\.env", _CONFIG)
    with _windows((ignore, FSExposeRule("D:\\a\\repo\\", False, _CONFIG))):
        result = guard_files._apply_dest_to_src_rules("D:\\a\\repo\\.env", write=False)
    assert result == (None, ignore)


def test_the_disarmed_test_rule_accepts_every_drive() -> None:
    with _windows():
        guard_files._deactivate_guard_files()
        results = [
            guard_files._apply_dest_to_src_rules(p, write=True)[0]
            for p in ("D:\\a\\repo\\", "C:\\Users\\runner\\AppData\\Local\\Temp\\x")
        ]
    guard_files._deactivate_guard_files()
    assert None not in results, results
