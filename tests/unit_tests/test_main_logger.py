# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for how main_logger shows a path."""

from pathlib import Path

import pytest

from pysandboxes.main_logger import config_log, make_relative_path


def test_a_path_outside_cwd_is_shown_even_without_a_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A qemu guest has neither HOME nor a passwd entry: Path.home() raises there.

    make_relative_path formats the rule of a denial, and a denied write of a .pyc
    runs through it. An exception here turned that harmless denial into a failed
    import.
    """

    def no_home() -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", staticmethod(no_home))
    outside = Path("/usr/lib/some.profile")

    assert make_relative_path(outside) == str(outside)


def test_windows_never_builds_a_rich_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """rich queries kernel32 through ctypes on Windows, which the API guard denies."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("rich must not be used on Windows")

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("rich.console.Console", forbidden)

    config_log(20, use_rich=True)
