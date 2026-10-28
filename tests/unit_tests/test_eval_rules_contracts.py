# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import re
from pathlib import Path

import pytest  # type: ignore[import-untyped]
from hypothesis import given, settings
from hypothesis import strategies as st

from pysandboxes.eval_rules import (
    NAMESPACE_MODES,
    SYNTAX_GROUPS,
    LearnEvalRule,
    generate_rules,
    parse_rules,
    parse_scalar,
)
from pysandboxes.sb_types import ConfigLine
from pysandboxes.tools import GlobPattern, remove_comments

INT_KEYS = ["eval-max-iterations", "eval-max-call-depth", "eval-max-depth", "eval-max-nodes", "eval-max-leaked-threads"]
counts = st.integers(min_value=0, max_value=10**9)


@pytest.mark.parametrize("key", INT_KEYS)
@given(counts)
def test_an_int_key_reads_the_digits_with_or_without_separators(key: str, n: int) -> None:
    assert parse_scalar(key, str(n)) == n
    assert parse_scalar(key, f"{n:_}") == n


@given(counts, st.sampled_from([("KB", 1_000), ("MB", 1_000_000), ("GB", 1_000_000_000)]), st.booleans())
def test_a_size_takes_a_decimal_suffix_in_any_case(n: int, unit: tuple[str, int], lower: bool) -> None:
    suffix, factor = unit
    assert parse_scalar("eval-max-alloc", f"{n}{suffix.lower() if lower else suffix}") == n * factor
    assert parse_scalar("eval-max-alloc", str(n)) == n


@given(st.integers(min_value=0, max_value=10**6), st.sampled_from([("ms", 0.001), ("s", 1.0), ("m", 60.0)]))
def test_a_duration_is_returned_in_seconds(n: int, unit: tuple[str, float]) -> None:
    suffix, factor = unit
    assert parse_scalar("eval-timeout", f"{n}{suffix}") == pytest.approx(n * factor)
    assert parse_scalar("eval-timeout", str(n)) == float(n)


@pytest.mark.parametrize("mode", NAMESPACE_MODES)
def test_a_namespace_mode_is_returned_as_is(mode: str) -> None:
    assert parse_scalar("eval-namespace", mode) == mode


@pytest.mark.parametrize(
    "key, value",
    [
        ("eval-namespace", "open"),
        ("eval-namespace", ""),
        ("eval-max-nodes", "abc"),
        ("eval-max-nodes", "1.5"),
        ("eval-max-nodes", ""),
        ("eval-max-alloc", "inf"),
        ("eval-timeout", "fast"),
        ("eval-max-depth", "DENY:3"),
        ("eval-max-depth", "3*"),
        ("eval-namespace", "DENY:closed"),
    ],
)
def test_a_malformed_scalar_raises_value_error(key: str, value: str) -> None:
    with pytest.raises(ValueError):
        parse_scalar(key, value)


@pytest.mark.xfail(
    strict=True, raises=Exception, reason="parse_scalar leaks OverflowError, parse_rules only catches ValueError"
)
@pytest.mark.parametrize("value", ["infMB", "1e400KB"])
def test_an_overflowing_size_is_reported_as_a_configuration_error(value: str) -> None:
    errors: list[tuple[str, Path, int]] = []
    parse_rules([ConfigLine(f"eval-max-alloc={value}", Path("p"), 1)], errors)
    assert len(errors) == 1


def _regex(glob: str) -> "re.Pattern[str]":
    return re.compile(re.escape(glob).replace(r"\*", "[^\n]*"), re.DOTALL)


globs = st.text(alphabet="ab*\n", max_size=8)
subjects = st.text(alphabet="ab\n", max_size=10)


@settings(max_examples=300)
@given(globs, subjects)
def test_glob_pattern_decides_the_same_language_as_the_anchored_regex(glob: str, subject: str) -> None:
    assert GlobPattern(glob).match(subject) == bool(_regex(glob).fullmatch(subject))


def test_glob_pattern_oracle_has_teeth() -> None:
    """Negative control: the oracle tells a match from a mismatch, so the property above can fail."""
    assert _regex("a*").fullmatch("abb") and not _regex("a*").fullmatch("ba")
    assert not _regex("a*").fullmatch("a\nb")


EVAL_NAMES = {
    "eval-call": st.from_regex(r"[a-z_][a-z0-9_]{0,8}", fullmatch=True),
    "eval-import": st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
    "eval-syntax": st.sampled_from(sorted({n for nodes in SYNTAX_GROUPS.values() for n in nodes})),
    "eval-attribute": st.sampled_from(["append", "upper", "get", "keys", "items", "split"]),
    "eval-magic": st.sampled_from(["__len__", "__iter__", "__str__", "__repr__"]),
}


@given(
    st.sets(
        st.one_of(*(st.builds(LearnEvalRule, st.just(key), names) for key, names in EVAL_NAMES.items())),
        min_size=1,
        max_size=12,
    )
)
def test_what_learning_emits_is_accepted_by_the_parser(learned: set[LearnEvalRule]) -> None:
    emitted = generate_rules(set(learned))
    config = [ConfigLine(line, Path("learned.profile"), n) for n, line in enumerate(remove_comments(emitted), start=1)]
    errors: list[tuple[str, Path, int]] = []
    profiles, others = parse_rules(config, errors)
    assert errors == []
    assert others == []
    assert len(profiles) == 1


def test_learning_nothing_emits_nothing() -> None:
    assert generate_rules(set()) == []
