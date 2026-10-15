# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Behaviour of `pysandboxes.tools` helpers that the other tests leave unobserved."""

import asyncio
import sys
from pathlib import Path

import pytest

from pysandboxes.tools import (
    GlobPattern,
    check_mixte_async_async,
    follow_links_executable,
    remove_comments,
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
