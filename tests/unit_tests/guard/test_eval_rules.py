# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The eval-* rule grammar and the exceptions the guard raises."""

import pickle
import random
import re
from pathlib import Path
from typing import cast

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import (
    EvalInterrupted,
    EvalSyntaxRejected,
    RuleEvalPermissionError,
    SandBoxError,
)
from pysandboxes.eval_rules import (
    ATTRIBUTE_GROUPS,
    CORE_NODES,
    DEFAULT_RULES,
    EMPTY_NAMES,
    SYNTAX_GROUPS,
    EvalProfiles,
    EvalRules,
    NameSet,
    parse_rules,
    parse_scalar,
)
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, ConfigLines


def _lines(*rules: str) -> ConfigLines:
    return [ConfigLine(rule, Path("profile"), n) for n, rule in enumerate(rules)]


def _profile(profiles: EvalProfiles, name: str = "") -> EvalRules:
    """Read one profile as an `EvalRules`.

    `ImmutableDict` subclasses `tuple[tuple[K, ...], tuple[V, ...]]`, so mypy
    resolves an indexing expression through `tuple.__getitem__` and rejects
    every attribute read on the result. The cast lives here, once, instead of
    as a `type: ignore` on each of the forty assertions below.
    """
    return cast(EvalRules, profiles[name])


def _parse(*rules: str) -> tuple[dict[str, EvalRules], list[ErrorMsg]]:
    errors: list[ErrorMsg] = []
    profiles, others = parse_rules(_lines(*rules), errors)
    assert not others, others
    return {name: _profile(profiles, name) for name in profiles}, errors


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
    assert err.hint is None


def test_a_hint_replaces_the_rule_to_add() -> None:
    """A refusal no configuration can lift must not name a key to add.

    Frame capture is the one implicit DENY of the design, so telling the
    reader to add `eval-attribute=gi_frame` would send them after a rule that
    changes nothing -- which reads as a broken guard, not as a deliberate
    denial.
    """
    err = RuleEvalPermissionError("gi_frame", "eval-attribute", "Frame capture is always refused.")
    assert "Add `eval-attribute=gi_frame`" not in str(err)
    assert "Frame capture is always refused." in str(err)
    assert pickle.loads(pickle.dumps(err)).hint == "Frame capture is always refused."


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


def test_no_eval_key_leaves_the_profile_undeclared() -> None:
    errors: list[ErrorMsg] = []
    profiles, others = parse_rules(_lines("py-sandbox=true"), errors)
    assert not errors
    assert len(others) == 1
    assert not profiles


def test_a_group_expands_to_its_nodes() -> None:
    profiles, errors = _parse("eval-syntax=loop")
    assert not errors
    rules = profiles[""]
    for node in ("For", "While", "Break", "Continue"):
        assert rules.syntax.allows(node)
    assert not rules.syntax.allows("ListComp")


def test_an_exact_node_name_is_accepted_beside_a_group() -> None:
    profiles, errors = _parse("eval-syntax=arith, Lambda")
    assert not errors
    rules = profiles[""]
    assert rules.syntax.allows("BinOp")
    assert rules.syntax.allows("Lambda")


def test_pass_is_in_the_core_so_a_class_or_try_body_can_exist() -> None:
    """No eval-syntax group names Pass, so the core is the only place it can
    come from. Without it, `class C: pass` is refused under every possible
    configuration, including one granting eval-syntax=class."""
    assert "Pass" in CORE_NODES


def test_the_minimal_core_is_always_allowed() -> None:
    profiles, _ = _parse("eval-syntax=arith")
    rules = profiles[""]
    for node in CORE_NODES:
        assert rules.syntax.allows(node)


def test_an_unknown_token_is_an_error_naming_the_closest_one() -> None:
    errors: list[ErrorMsg] = []
    parse_rules(_lines("eval-syntax=lop"), errors)
    assert len(errors) == 1
    assert "lop" in errors[0][0]
    assert "loop" in errors[0][0]


def test_repeating_a_key_unions_its_values() -> None:
    profiles, errors = _parse("eval-call=len", "eval-call=range")
    assert not errors
    rules = profiles[""]
    assert rules.call.allows("len")
    assert rules.call.allows("range")


def test_rule_order_carries_no_meaning() -> None:
    rules = [
        "eval-syntax=arith",
        "eval-call=len, range",
        "eval-call=DENY:range",
        "eval-attribute=get*",
        "eval-timeout=2s",
    ]
    reference, _ = _parse(*rules)
    for _ in range(5):
        shuffled = rules[:]
        random.shuffle(shuffled)
        other, _ = _parse(*shuffled)
        assert other[""] == reference[""]


def test_deny_wins_from_any_position() -> None:
    before, _ = _parse("eval-call=DENY:range", "eval-call=len, range")
    after, _ = _parse("eval-call=len, range", "eval-call=DENY:range")
    assert not before[""].call.allows("range")
    assert not after[""].call.allows("range")


def test_a_pattern_grants_every_matching_name() -> None:
    profiles, errors = _parse("eval-attribute=get*, is*")
    assert not errors
    rules = profiles[""]
    assert rules.attribute.allows("get_name")
    assert rules.attribute.allows("isdigit")
    assert not rules.attribute.allows("split")


def test_a_pattern_is_anchored_on_both_ends() -> None:
    profiles, _ = _parse("eval-attribute=get*")
    assert not profiles[""].attribute.allows("forget_me")


def test_a_pattern_on_eval_syntax_is_an_error() -> None:
    errors: list[ErrorMsg] = []
    parse_rules(_lines("eval-syntax=Bin*"), errors)
    assert len(errors) == 1
    assert "pattern" in errors[0][0].lower()


def test_a_wide_pattern_warns_with_its_expansion(caplog: pytest.LogCaptureFixture) -> None:
    errors: list[ErrorMsg] = []
    with caplog.at_level("WARNING"):
        parse_rules(_lines("eval-attribute=ge*"), errors)
    assert not errors
    assert any("expands to" in record.getMessage() for record in caplog.records)


def test_a_bare_star_warns() -> None:
    errors: list[ErrorMsg] = []
    profiles, _ = parse_rules(_lines("eval-attribute=*"), errors)
    assert not errors
    assert _profile(profiles).attribute.allows("anything")


def test_str_methods_excludes_format_and_format_map() -> None:
    assert "split" in ATTRIBUTE_GROUPS["str-methods"]
    assert "format" not in ATTRIBUTE_GROUPS["str-methods"]
    assert "format_map" not in ATTRIBUTE_GROUPS["str-methods"]


def test_granting_format_by_name_warns(caplog: pytest.LogCaptureFixture) -> None:
    errors: list[ErrorMsg] = []
    with caplog.at_level("WARNING"):
        profiles, _ = parse_rules(_lines("eval-attribute=format"), errors)
    assert not errors
    assert _profile(profiles).attribute.allows("format")
    assert any("4bis.a" in record.getMessage() for record in caplog.records)


def test_attribute_groups_follow_the_running_interpreter() -> None:
    assert ATTRIBUTE_GROUPS["list-methods"] == frozenset(n for n in dir(list) if not n.startswith("_"))


def test_a_profile_is_independent_of_the_default() -> None:
    profiles, errors = _parse(
        "eval-syntax=arith, compare, loop",
        "eval-timeout=5s",
        "eval-syntax:llm=arith",
        "eval-timeout:llm=2s",
    )
    assert not errors
    assert profiles["llm"].syntax.allows("BinOp")
    assert not profiles["llm"].syntax.allows("While")
    assert profiles["llm"].timeout == 2.0
    assert profiles[""].timeout == 5.0


def test_a_profile_gets_the_scalar_defaults_it_does_not_set() -> None:
    profiles, _ = _parse("eval-syntax:llm=arith")
    assert profiles["llm"].max_nodes == 5_000


def test_a_repeated_scalar_key_is_a_configuration_error() -> None:
    errors: list[ErrorMsg] = []
    parse_rules(_lines("eval-timeout=2s", "eval-timeout=5s"), errors)
    assert len(errors) == 1
    assert "eval-timeout" in errors[0][0]


def test_a_repeated_scalar_key_in_another_profile_is_not_an_error() -> None:
    errors: list[ErrorMsg] = []
    parse_rules(_lines("eval-timeout=2s", "eval-timeout:llm=5s"), errors)
    assert not errors


def test_an_unknown_eval_key_is_an_error() -> None:
    errors: list[ErrorMsg] = []
    parse_rules(_lines("eval-maximum-nodes=10"), errors)
    assert len(errors) == 1
    assert "eval-maximum-nodes" in errors[0][0]


def test_an_import_pattern_is_accepted() -> None:
    profiles, errors = _parse("eval-import=json.*")
    assert not errors
    assert profiles[""].imports.allows("json.decoder")


def test_syntax_groups_only_name_real_ast_nodes() -> None:
    import ast

    for nodes in SYNTAX_GROUPS.values():
        for node in nodes:
            assert hasattr(ast, node), node
