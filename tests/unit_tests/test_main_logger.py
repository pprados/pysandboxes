# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for how main_logger shows a path."""

from pathlib import Path

import pytest

from pysandboxes.main_logger import config_log, format_error_list, make_relative_path


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


def test_a_path_given_as_text_is_shown_relative_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert make_relative_path(str(tmp_path / "conf" / "a.profile")) == str(Path("conf") / "a.profile")


@pytest.mark.parametrize(
    ("errors", "text"),
    [(["only"], "only"), (["b", "a"], "a and b"), (["c", "a", "b"], "a, b and c")],
)
def test_errors_are_listed_sorted_with_a_final_and(errors: list[str], text: str) -> None:
    assert format_error_list(errors) == text


@pytest.mark.parametrize(("use_rich", "built"), [(True, True), (False, False)])
def test_the_rich_console_is_built_only_when_asked_outside_windows(
    monkeypatch: pytest.MonkeyPatch, use_rich: bool, built: bool
) -> None:
    calls: list[object] = []

    def console(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        raise ImportError("stop after the call")

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("rich.console.Console", console)

    config_log(20, use_rich=use_rich)

    assert bool(calls) is built
