# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Properties of the parsers, checked on generated inputs rather than on hand-picked ones."""

import re
from typing import Literal

from hypothesis import given, settings
from hypothesis import strategies as st

from pysandboxes.remote.parse_cpython_args import parse_python_cmd_line
from pysandboxes.tools import GlobPattern, _remove_comment, resolve_env_variables

_CS: tuple[Literal["Cs"]] = ("Cs",)
_LL: tuple[Literal["Ll"]] = ("Ll",)
_GLOB_ALPHABET = st.sampled_from(["a", "b", "*", "\n"])
_SUBJECT_ALPHABET = st.sampled_from(["a", "b", "\n"])
_WORD = st.text(alphabet=st.characters(exclude_characters="-\x00", exclude_categories=_CS), min_size=1)


def _reference_glob(glob: str) -> re.Pattern[str]:
    """What the two-pointer scan must decide: `*` is any run of characters but a newline."""
    return re.compile("".join("[^\n]*" if ch == "*" else re.escape(ch) for ch in glob), re.DOTALL)


@settings(max_examples=300, deadline=None)
@given(st.text(_GLOB_ALPHABET, max_size=8), st.text(_SUBJECT_ALPHABET, max_size=10))
def test_the_glob_scan_decides_the_same_language_as_its_regex(glob: str, subject: str) -> None:
    assert GlobPattern(glob).match(subject) == bool(_reference_glob(glob).fullmatch(subject))


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=40))
def test_a_comment_is_cut_off_and_nothing_else_is_added(line: str) -> None:
    cleaned = _remove_comment(line)

    assert line.startswith(cleaned)
    assert _remove_comment(cleaned) == cleaned


@settings(max_examples=200, deadline=None)
@given(st.text(st.characters(exclude_characters="#'\"", exclude_categories=_CS), max_size=40))
def test_a_line_without_quote_keeps_what_precedes_its_hash_without_trailing_blanks(text: str) -> None:
    assert _remove_comment(text + "# trailing") == text.rstrip()
    assert _remove_comment(text) == text.rstrip()


@settings(max_examples=200, deadline=None)
@given(st.text(st.characters(exclude_characters="$\\", exclude_categories=_CS), max_size=40))
def test_a_string_without_reference_is_left_alone(text: str) -> None:
    assert resolve_env_variables(text, {"HOME": "/h"}) == text


@settings(max_examples=200, deadline=None)
@given(
    st.text(st.characters(exclude_characters="$\\{}", exclude_categories=_CS), max_size=10),
    st.text(st.characters(exclude_characters="$\\{}", exclude_categories=_CS), max_size=10),
    st.text(st.characters(exclude_characters="$\\{}:", exclude_categories=_CS), max_size=10),
)
def test_a_reference_is_replaced_by_its_value_or_its_default(before: str, value: str, default: str) -> None:
    assert resolve_env_variables(f"{before}${{A}}", {"A": value}) == before + value
    assert resolve_env_variables(f"{before}${{A:-{default}}}", {}) == before + default


@settings(max_examples=200, deadline=None)
@given(st.lists(_WORD, min_size=1, max_size=5))
def test_a_command_line_without_option_is_all_program(words: list[str]) -> None:
    parsed, sandboxes, run, _ = parse_python_cmd_line(list(words))

    assert (parsed, sandboxes, run) == ([], [], words)


@settings(max_examples=200, deadline=None)
@given(st.text(st.characters(categories=_LL), min_size=1, max_size=8), st.lists(_WORD, max_size=4))
def test_dash_m_hands_the_module_and_the_rest_to_the_program(module: str, rest: list[str]) -> None:
    _, _, run, _ = parse_python_cmd_line(["-m", module, *rest])

    assert run == ["-m", module, *rest]
