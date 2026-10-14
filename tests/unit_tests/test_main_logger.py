# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unit tests for how main_logger shows a path."""

import logging
from pathlib import Path

import pytest

from pysandboxes.main_logger import config_log, format_error_list, make_relative_path


@pytest.fixture(autouse=True)
def _isolated_root_logger(monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """`config_log` replaces the handlers and the level of the root logger: give each test a private set."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    monkeypatch.setattr(root, "level", root.level)
    return root


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


def test_the_root_logger_gets_one_handler_at_the_requested_level_and_format(
    _isolated_root_logger: logging.Logger,
) -> None:
    root = _isolated_root_logger
    root.addHandler(logging.NullHandler())

    config_log(logging.DEBUG, "%(levelname)s/%(message)s")

    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert root.handlers[0].formatter is not None
    assert root.handlers[0].formatter._fmt == "%(levelname)s/%(message)s"


def test_the_default_format_names_the_process_and_the_logger(_isolated_root_logger: logging.Logger) -> None:
    config_log(logging.WARNING)

    formatter = _isolated_root_logger.handlers[0].formatter
    assert formatter is not None
    assert formatter._fmt == "%(levelname)-5s [%(process)d] %(name)s: %(message)s"


def test_a_rich_handler_replaces_the_plain_one_when_asked(_isolated_root_logger: logging.Logger) -> None:
    from rich.logging import RichHandler

    config_log(logging.INFO, use_rich=True)

    assert [type(handler) for handler in _isolated_root_logger.handlers] == [RichHandler]
