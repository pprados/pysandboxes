# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Fuzz the profile parser: any text yields rules or a ConfigSyntaxError, never another exception."""

from pathlib import Path
from typing import Literal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pysandboxes.e import ConfigSyntaxError
from pysandboxes.py_sandbox import parse_config
from pysandboxes.sb_types import ConfigLine

_PREFIXES = [
    "env=",
    "unenv=",
    "expose-ro=",
    "expose-rw=",
    "ignore=",
    "allow-connect=",
    "allow-bind=",
    "python-api=",
    "python-import=",
    "os-sandbox=",
    "port=",
    "eval-",
    "remote-result-guard=",
    "learn=",
    "",
]
_SURROGATE: tuple[Literal["Cs"]] = ("Cs",)
_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=_SURROGATE, blacklist_characters="\x00\n\r"),
    max_size=60,
)
_LINE = st.builds(lambda prefix, tail: prefix + tail, st.sampled_from(_PREFIXES), _TEXT)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_LINE.filter(lambda line: not line.startswith("include")), max_size=8))
def test_any_profile_is_rules_or_a_syntax_error(lines: list[str]) -> None:
    config = [ConfigLine(line, Path("fuzz.profile"), ln) for ln, line in enumerate(lines, 1)]
    try:
        parse_config(config, Path("fuzz.profile"), envs={})
    except ConfigSyntaxError as error:
        assert error.errors


@pytest.mark.parametrize(
    "line",
    ["expose-ro=~nosuchuser_xyz/data", "expose-rw=~nosuchuser_xyz", 'include "~nosuchuser_xyz/x.profile"'],
)
def test_an_unknown_user_home_is_a_syntax_error(line: str) -> None:
    with pytest.raises(ConfigSyntaxError):
        parse_config([ConfigLine(line, Path("p.profile"), 1)], Path("p.profile"), envs={})
