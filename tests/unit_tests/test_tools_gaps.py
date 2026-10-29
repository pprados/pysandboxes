# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Behaviour of `pysandboxes.tools` helpers that the other tests leave unobserved."""

import asyncio
import functools
import importlib.util
import sys
from pathlib import Path

import pytest

from pysandboxes.sb_types import ConfigLine
from pysandboxes.tools import (
    GlobPattern,
    check_mixte_async_async,
    find_config_for_module,
    follow_links_executable,
    get_callable_info,
    remove_comments,
    remove_config_comments,
    resolve_env_variables,
)


@pytest.mark.parametrize("reserved", ["", ""])
def test_either_reserved_marker_character_alone_is_refused(reserved: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        resolve_env_variables(f"a{reserved}b", {})


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('"a " # comment', '"a "'),
        ("'a ' # comment", "'a '"),
        ('"a \\" # kept" # comment', '"a \\" # kept"'),
    ],
)
def test_a_comment_after_a_quoted_value_is_removed_and_one_inside_it_kept(line: str, expected: str) -> None:
    assert remove_comments([line]) == [expected]


def test_mixing_sync_and_async_inside_a_running_loop_is_refused() -> None:
    async def inside() -> None:
        check_mixte_async_async()

    with pytest.raises(RuntimeError, match="mix synchronous and asynchronous"):
        asyncio.run(inside())


def test_outside_a_running_loop_the_check_passes() -> None:
    check_mixte_async_async()


def test_the_base_prefix_is_only_added_for_a_windows_venv(tmp_path: Path) -> None:
    executable = tmp_path / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text("")

    paths = follow_links_executable(executable, set())

    assert (sys.platform == "win32") == (Path(sys.base_prefix) in paths)


def test_a_star_swallows_control_characters_other_than_a_newline() -> None:
    assert GlobPattern("a*b").match("a\tb")
    assert GlobPattern("a*b").match("a\x01b")
    assert not GlobPattern("a*b").match("a\nb")


def test_a_glob_longer_than_the_small_integer_cache_matches() -> None:
    long_name = "a" * 300

    assert GlobPattern(long_name).match(long_name)
    assert GlobPattern("*" + long_name + "*").match("b" + long_name + "b")
    assert not GlobPattern(long_name).match(long_name + "b")
    assert not GlobPattern(long_name + "b").match(long_name)


def test_template_lines_are_dropped_with_the_comments_and_the_empty_lines() -> None:
    lines = [
        ConfigLine(text, Path("p"), n) for n, text in enumerate(["{template}", "# note", "", "net=ALLOW", "env=A # x"])
    ]

    assert [line.rule for line in remove_config_comments(lines)] == ["net=ALLOW", "env=A"]


def test_a_missing_module_has_no_config() -> None:
    assert find_config_for_module("no_such_package_for_sure.sub", ".py-sandboxes") is None


def test_a_module_that_cannot_be_read_has_no_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(name: str) -> None:
        raise FileNotFoundError(name)

    monkeypatch.setattr(importlib.util, "find_spec", broken)

    assert find_config_for_module("os", ".py-sandboxes") is None


def test_a_callable_without_qualname_is_named_after_its_name() -> None:
    class Named:
        def __call__(self) -> None: ...

    named = Named()
    named.__name__ = "renamed"  # type: ignore[attr-defined]

    assert get_callable_info(named)[1] == "renamed"


def test_a_callable_instance_is_named_after_its_class() -> None:
    assert get_callable_info(functools.partial(print))[1] == "partial.__call__"


def test_a_system_interpreter_adds_no_path_to_expose(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for prefix in ("/usr/bin", "/usr/local/bin"):
        monkeypatch.setattr(Path, "resolve", lambda self, strict=False, prefix=prefix: Path(prefix) / "python3")
        paths: set[Path] = set()

        follow_links_executable(tmp_path / "python3", paths)

        assert not paths


def test_a_bound_method_and_a_class_are_named_by_their_qualified_name() -> None:
    """Both always carry a `__qualname__`: no other lookup is needed to name them."""

    class Holder:
        def method(self) -> None: ...

    assert (
        get_callable_info(Holder().method)[1]
        == "test_a_bound_method_and_a_class_are_named_by_their_qualified_name.<locals>.Holder.method"
    )
    assert get_callable_info(Holder)[1].endswith("<locals>.Holder")  # type: ignore[union-attr]
