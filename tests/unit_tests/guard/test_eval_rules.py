# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The eval-* rule grammar and the exceptions the guard raises."""

import pickle
import re

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import (
    EvalInterrupted,
    EvalSyntaxRejected,
    RuleEvalPermissionError,
    SandBoxError,
    SandboxContextWarning,
)
from pysandboxes.eval_rules import DEFAULT_RULES, EMPTY_NAMES, NameSet, parse_scalar


def test_eval_syntax_rejected_is_a_syntax_error_and_a_sandbox_error() -> None:
    err = EvalSyntaxRejected(
        "1 rule violated in <eval>",
        ["line 1, col 0: 'While' is not allowed"],
        lineno=1,
        offset=0,
        text="while True: pass",
    )
    assert isinstance(err, SyntaxError)
    assert isinstance(err, SandBoxError)
    assert err.violations == ["line 1, col 0: 'While' is not allowed"]
    assert err.lineno == 1
    assert err.text == "while True: pass"


def test_eval_interrupted_is_not_an_exception() -> None:
    """A bare `except Exception:` inside evaluated code must not catch it."""
    err = EvalInterrupted("eval-timeout=5s exhausted")
    assert isinstance(err, BaseException)
    assert not isinstance(err, Exception)
    assert err.reason == "eval-timeout=5s exhausted"


def test_rule_eval_permission_error_names_the_rule_to_add() -> None:
    err = RuleEvalPermissionError("__class__", "eval-magic")
    assert isinstance(err, PermissionError)
    assert isinstance(err, SandBoxError)
    assert "eval-magic=__class__" in str(err)
    assert err.target == "__class__"
    assert err.rule_key == "eval-magic"


def test_rule_eval_permission_error_survives_the_transport() -> None:
    """The sandbox pickles refusals back to the caller."""
    err = pickle.loads(pickle.dumps(RuleEvalPermissionError("split", "eval-attribute")))
    assert err.target == "split"
    assert err.rule_key == "eval-attribute"


def test_sandbox_context_warning_is_a_warning() -> None:
    assert issubclass(SandboxContextWarning, Warning)


def test_parse_scalar_accepts_digit_separators() -> None:
    assert parse_scalar("eval-max-iterations", "1_000_000") == 1_000_000


def test_parse_scalar_accepts_decimal_size_suffixes() -> None:
    assert parse_scalar("eval-max-alloc", "10MB") == 10_000_000
    assert parse_scalar("eval-max-alloc", "512KB") == 512_000
    assert parse_scalar("eval-max-alloc", "1GB") == 1_000_000_000


def test_parse_scalar_accepts_duration_suffixes() -> None:
    assert parse_scalar("eval-timeout", "5s") == 5.0
    assert parse_scalar("eval-timeout", "250ms") == 0.25
    assert parse_scalar("eval-timeout", "2m") == 120.0


def test_parse_scalar_rejects_a_deny_prefix() -> None:
    """DENY: and patterns are list-key only (spec 3)."""
    with pytest.raises(ValueError, match="list keys only"):
        parse_scalar("eval-timeout", "DENY:5s")


def test_parse_scalar_rejects_a_pattern() -> None:
    with pytest.raises(ValueError, match="list keys only"):
        parse_scalar("eval-namespace", "closed*")


def test_parse_scalar_rejects_an_unknown_namespace_mode() -> None:
    with pytest.raises(ValueError, match="adaptive"):
        parse_scalar("eval-namespace", "open")


def test_parse_scalar_rejects_a_size_suffix_on_a_duration() -> None:
    with pytest.raises(ValueError):
        parse_scalar("eval-timeout", "10MB")


def test_defaults_match_the_spec() -> None:
    assert DEFAULT_RULES.declared is False
    assert DEFAULT_RULES.namespace == "adaptive"
    assert DEFAULT_RULES.max_iterations == 1_000_000
    assert DEFAULT_RULES.max_call_depth == 20
    assert DEFAULT_RULES.max_depth == 20
    assert DEFAULT_RULES.max_nodes == 5_000
    assert DEFAULT_RULES.max_alloc == 10_000_000
    assert DEFAULT_RULES.timeout == 5.0
    assert DEFAULT_RULES.max_leaked_threads == 4


def test_an_empty_name_set_allows_nothing() -> None:
    assert not EMPTY_NAMES.allows("len")


def test_deny_wins_over_an_allow_pattern() -> None:
    names = NameSet(
        allow=frozenset(),
        allow_patterns=(re.compile(r"get.*\Z"),),
        deny=frozenset({"get_secret"}),
        deny_patterns=(),
    )
    assert names.allows("get_name")
    assert not names.allows("get_secret")


def test_deny_wins_over_an_explicit_allow() -> None:
    names = NameSet(
        allow=frozenset({"open"}),
        allow_patterns=(),
        deny=frozenset({"open"}),
        deny_patterns=(),
    )
    assert not names.allows("open")
