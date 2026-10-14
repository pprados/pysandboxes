# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Metamorphic tests: transformations of a profile that must not change what it grants."""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from pysandboxes import guard_envs
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

_SOURCE = {"DUMMY_KEY": "abc", "OTHER_KEY": "def", "DUMMY_NAME": "ghi", "PLAIN": "jkl"}
_LINES = [
    "env=DUMMY_KEY=${DUMMY_KEY}",
    "env=OTHER_KEY=${OTHER_KEY}",
    "env=DUMMY_NAME=${DUMMY_NAME}",
    "env=PLAIN=${PLAIN}",
    "env=LITERAL=value",
]


def _envs(lines: list[str]) -> dict[str, str]:
    errors: list[ErrorMsg] = []
    _, envs, unclaimed = guard_envs.parse_rules(
        [ConfigLine(line, Path("profile"), ln) for ln, line in enumerate(lines, 1)], _SOURCE, errors
    )
    assert errors == []
    assert unclaimed == []
    return dict(envs)


@given(st.lists(st.sampled_from(_LINES), min_size=1, unique=True).flatmap(st.permutations))
def test_env_rule_order_does_not_change_the_grant(lines: list[str]) -> None:
    assert _envs(lines) == _envs(sorted(lines))


@given(st.lists(st.sampled_from(_LINES), min_size=1, unique=True), st.data())
def test_duplicated_env_rules_do_not_change_the_grant(lines: list[str], data: st.DataObject) -> None:
    extra = data.draw(st.sampled_from(lines))
    assert _envs([*lines, extra]) == _envs(lines)


@given(st.lists(st.sampled_from(_LINES), min_size=1, unique=True), st.data())
def test_unenv_removes_exactly_what_it_names(lines: list[str], data: st.DataObject) -> None:
    granted = _envs(lines)
    name = data.draw(st.sampled_from(sorted(granted)))
    assert _envs([*lines, f"unenv={name}"]) == {k: v for k, v in granted.items() if k != name}
