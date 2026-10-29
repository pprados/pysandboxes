# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The `__sb_*` helpers, each in isolation."""

import logging
import re
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalInterrupted, RuleEvalPermissionError
from pysandboxes.eval_rules import DEFAULT_RULES, NameSet
from pysandboxes.eval_runtime import (
    FRAME_CAPTURE,
    HELPERS,
    EvalState,
    __sb_b_dir__,
    __sb_binop__,
    __sb_enter__,
    __sb_getattr__,
    __sb_iter__,
    __sb_leave__,
    __sb_tick__,
    __sb_writable__,
    _reset_regex_warnings,
    check_format_spec,
    pop_state,
    push_state,
)
from pysandboxes.tools import GlobPattern


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


@pytest.fixture
def state() -> Iterator[EvalState]:
    rules = DEFAULT_RULES._replace(
        attribute=_names("split", "upper"),
        magic=_names("__name__"),
        max_iterations=5,
        max_call_depth=3,
        max_alloc=1_000,
    )
    st = EvalState(rules)
    push_state(st)
    yield st
    pop_state()


def test_tick_counts_and_interrupts(state: EvalState) -> None:
    for _ in range(5):
        __sb_tick__()
    with pytest.raises(EvalInterrupted, match="eval-max-iterations=5"):
        __sb_tick__()


def test_tick_honours_the_watchdog_flag(state: EvalState) -> None:
    state.interrupted = True
    state.reason = "eval-timeout=5s"
    with pytest.raises(EvalInterrupted, match="eval-timeout=5s"):
        __sb_tick__()


def test_enter_and_leave_bound_the_call_depth(state: EvalState) -> None:
    for _ in range(3):
        __sb_enter__()
    with pytest.raises(EvalInterrupted, match="eval-max-call-depth=3"):
        __sb_enter__()


def test_leave_restores_the_depth(state: EvalState) -> None:
    __sb_enter__()
    __sb_leave__()
    assert state.depth == 0


def test_a_refused_enter_does_not_leak_depth(state: EvalState) -> None:
    """The failing frame never runs, so it must not be counted."""
    for _ in range(3):
        __sb_enter__()
    with pytest.raises(EvalInterrupted):
        __sb_enter__()
    assert state.depth == 3


def test_getattr_allows_a_declared_name(state: EvalState) -> None:
    assert __sb_getattr__("a b", "split")() == ["a", "b"]
    assert __sb_getattr__("ab", "upper")() == "AB"


def test_getattr_refuses_an_undeclared_name(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-attribute=strip"):
        __sb_getattr__("ab", "strip")


def test_getattr_refuses_an_undeclared_dunder(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-magic=__class__"):
        __sb_getattr__(object(), "__class__")


def test_getattr_allows_a_declared_dunder(state: EvalState) -> None:
    assert __sb_getattr__(re, "__name__") == "re"


def test_frame_capture_survives_a_wide_attribute_rule() -> None:
    """Family 3 of spec 7 is an implicit DENY no configuration can override."""
    wide = NameSet(allow=frozenset(), allow_patterns=(GlobPattern("*"),), deny=frozenset(), deny_patterns=())
    push_state(EvalState(DEFAULT_RULES._replace(attribute=wide, magic=wide)))
    try:
        for name in ("gi_frame", "f_globals", "cr_frame", "tb_frame"):
            with pytest.raises(RuleEvalPermissionError, match=name):
                __sb_getattr__(object(), name)
    finally:
        pop_state()


def test_a_frame_capture_refusal_names_no_rule_to_add() -> None:
    """Nothing lifts this denial, so the message must not send the reader
    after a rule that changes nothing.

    No state is pushed on purpose: passing without one proves FRAME_CAPTURE
    is consulted before any state lookup. Adding the `state` fixture here
    would make the test pass either way and silently drop that guarantee --
    a `RuntimeError` from this test means the check was moved below
    `current_state()`.
    """
    with pytest.raises(RuleEvalPermissionError) as caught:
        __sb_getattr__(object(), "f_globals")
    assert "Add `eval-attribute=f_globals`" not in str(caught.value)
    assert caught.value.hint is not None


class _Holder:
    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)


@pytest.fixture
def wide_state() -> Iterator[EvalState]:
    rules = DEFAULT_RULES._replace(
        attribute=_names("ok", "f_globals", "__lead", "trail__"),
        magic=_names("__name__"),
    )
    st = EvalState(rules)
    push_state(st)
    yield st
    pop_state()


def test_dir_hides_a_frame_capture_name_even_when_the_rules_allow_it(wide_state: EvalState) -> None:
    assert __sb_b_dir__(_Holder(ok=1, f_globals=2)) == ["ok"]


def test_dir_judges_a_half_dunder_name_by_the_attribute_rules(wide_state: EvalState) -> None:
    """A name that only starts or only ends with `__` is not a magic name."""
    assert __sb_b_dir__(_Holder(__lead=1, trail__=2)) == ["__lead", "trail__"]


def test_frame_capture_covers_the_documented_names() -> None:
    assert {"gi_frame", "gi_code", "cr_frame", "ag_frame", "f_globals", "f_locals", "tb_next"} <= FRAME_CAPTURE


def test_learning_records_instead_of_refusing() -> None:
    push_state(EvalState(DEFAULT_RULES, learn=True))
    try:
        assert __sb_getattr__("ab", "strip")() == "ab"
        assert __sb_getattr__(re, "__name__") == "re"
    finally:
        st = pop_state()
    assert "strip" in st.attributes
    assert "__name__" in st.magic


def test_learning_still_refuses_frame_capture() -> None:
    push_state(EvalState(DEFAULT_RULES, learn=True))
    try:
        with pytest.raises(RuleEvalPermissionError):
            __sb_getattr__(object(), "f_globals")
    finally:
        pop_state()


def test_binop_passes_ordinary_operations_through(state: EvalState) -> None:
    assert __sb_binop__("+", 1, 2) == 3
    assert __sb_binop__("*", 3, 4) == 12
    assert __sb_binop__("**", 2, 10) == 1024


def test_binop_refuses_a_huge_power_before_computing(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        __sb_binop__("**", 10, 10**9)


def test_binop_refuses_a_sequence_repetition_over_the_budget(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        __sb_binop__("*", [0], 10**10)


@pytest.fixture
def regex_state() -> Iterator[EvalState]:
    rules = DEFAULT_RULES._replace(attribute=_names("match", "IGNORECASE"), magic=_names())
    st = EvalState(rules)
    push_state(st)
    _reset_regex_warnings()
    yield st
    pop_state()
    _reset_regex_warnings()


def test_reaching_the_stdlib_engine_is_reported(regex_state: EvalState, caplog: Any) -> None:
    """A finding, not a refusal: the read succeeds, and the message names the linear engine."""
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    assert __sb_getattr__(re, "match") is re.match
    assert len(caplog.records) == 1
    assert "re2" in caplog.records[0].getMessage()


def test_a_compiled_pattern_is_reported_too(regex_state: EvalState, caplog: Any) -> None:
    """A pattern the host compiled and passed in never crosses `re`, but its method does."""
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    __sb_getattr__(re.compile(r"a+"), "match")
    assert len(caplog.records) == 1


def test_a_substituted_engine_is_silent(regex_state: EvalState, caplog: Any) -> None:
    """Identity, not the name: whoever followed the advice stops being told to follow it."""
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    linear = type("FakeRe2", (), {"match": staticmethod(lambda s: None)})()
    __sb_getattr__(linear, "match")
    assert caplog.records == []


def test_a_non_engine_attribute_is_silent(regex_state: EvalState, caplog: Any) -> None:
    """Reading a flag starts no engine."""
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    __sb_getattr__(re, "IGNORECASE")
    assert caplog.records == []


def test_the_report_fires_once_per_attribute(regex_state: EvalState, caplog: Any) -> None:
    """A match inside a loop must not flood the log it is meant to be read in."""
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    for _ in range(5):
        __sb_getattr__(re, "match")
    assert len(caplog.records) == 1


def test_binop_refuses_a_sequence_repetition_written_the_other_way(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        __sb_binop__("*", 10**10, "a")


def test_binop_refuses_a_sequence_concatenation_over_the_budget(state: EvalState) -> None:
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        __sb_binop__("+", "a" * 900, "b" * 900)


def test_iter_ticks_once_per_item(state: EvalState) -> None:
    assert list(__sb_iter__([1, 2, 3])) == [1, 2, 3]
    assert state.iterations == 3


def test_iter_is_interruptible(state: EvalState) -> None:
    def forever() -> Iterator[int]:
        while True:
            yield 1

    # Both generators are abandoned mid-iteration on purpose: that is what an
    # interruption looks like from inside a comprehension. Do not close them.
    with pytest.raises(EvalInterrupted):
        list(__sb_iter__(forever()))


def test_helpers_exposes_exactly_the_nine_names() -> None:
    assert set(HELPERS) == {
        "__sb_tick__",
        "__sb_enter__",
        "__sb_leave__",
        "__sb_func__",
        "__sb_getattr__",
        "__sb_binop__",
        "__sb_iter__",
        "__sb_writable__",
        "__sb_format__",
    }


def test_an_exhausted_iteration_budget_stays_interrupted_across_helpers(state: EvalState) -> None:
    """A bare `except:` around the raise must not let the next call through."""
    for _ in range(5):
        __sb_tick__()
    try:
        __sb_tick__()
    except EvalInterrupted:
        pass
    with pytest.raises(EvalInterrupted):
        __sb_enter__()


def test_an_exhausted_call_depth_budget_stays_interrupted_across_helpers(state: EvalState) -> None:
    for _ in range(3):
        __sb_enter__()
    try:
        __sb_enter__()
    except EvalInterrupted:
        pass
    with pytest.raises(EvalInterrupted):
        __sb_tick__()


def test_call_depth_budget_holds_past_the_small_int_cache() -> None:
    """500 is outside CPython's small-int cache (-5..256): `is` would miss it."""
    rules = DEFAULT_RULES._replace(max_call_depth=500)
    push_state(EvalState(rules))
    try:
        for _ in range(500):
            __sb_enter__()
        with pytest.raises(EvalInterrupted, match="eval-max-call-depth=500"):
            __sb_enter__()
    finally:
        pop_state()


def test_a_name_must_satisfy_both_dunder_ends_to_route_as_magic() -> None:
    """`__custom` starts with `__` but does not end with it: an ordinary attribute."""
    rules = DEFAULT_RULES._replace(
        attribute=NameSet(allow=frozenset(), allow_patterns=(), deny=frozenset({"__custom"}), deny_patterns=()),
        magic=_names("__custom"),
    )
    push_state(EvalState(rules))
    try:
        with pytest.raises(RuleEvalPermissionError, match="eval-attribute=__custom"):
            __sb_getattr__(object(), "__custom")
    finally:
        pop_state()


def test_check_format_spec_allows_a_width_exactly_as_long_as_the_budgets_digit_count(state: EvalState) -> None:
    """max_alloc=1000 is 4 digits; a 4-digit width under it must not be short-circuited."""
    check_format_spec("0999d")


def test_binop_percent_with_a_star_width_ignores_non_int_arguments(state: EvalState) -> None:
    assert __sb_binop__("%", "%*d %s", (5, 1, "ab")) == "    1 ab"


class _EqualToRe:
    def match(self, *_args: Any) -> None:
        return None

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


def test_the_regex_warning_identity_check_rejects_an_equal_impostor(regex_state: EvalState, caplog: Any) -> None:
    caplog.set_level(logging.WARNING, logger="pysandboxes.eval_runtime")
    __sb_getattr__(_EqualToRe(), "match")
    assert caplog.records == []


def test_binop_power_guard_does_not_crash_on_non_int_operands(state: EvalState) -> None:
    assert __sb_binop__("**", 5, 2j) == 5**2j


def test_binop_allows_a_trivial_base_with_a_huge_exponent(state: EvalState) -> None:
    assert __sb_binop__("**", 1, 10**9) == 1


def test_binop_power_exactly_at_the_budget_boundary_is_allowed(state: EvalState) -> None:
    """bit_length(200) * 1000 == max_alloc(1000) * 8 exactly."""
    assert __sb_binop__("**", 200, 1000) == 200**1000


def test_binop_left_shift_by_zero_is_always_allowed(state: EvalState) -> None:
    huge = 2**100_000
    assert __sb_binop__("<<", huge, 0) == huge


def test_binop_left_shift_exactly_at_the_budget_boundary_is_allowed(state: EvalState) -> None:
    """bit_length(2**7998) == 7999; 7999 + 1 == max_alloc(1000) * 8 exactly."""
    left = 2**7998
    assert __sb_binop__("<<", left, 1) == left << 1


def test_binop_sequence_repetition_exactly_at_the_budget_is_allowed(state: EvalState) -> None:
    result = __sb_binop__("*", [0] * 10, 100)
    assert len(result) == 1000


def test_binop_plus_with_a_non_sequence_operand_fails_natively(state: EvalState) -> None:
    with pytest.raises(TypeError, match="unsupported operand"):
        __sb_binop__("+", 5, "hi")


def test_binop_sequence_concatenation_exactly_at_the_budget_is_allowed(state: EvalState) -> None:
    result = __sb_binop__("+", "a" * 500, "b" * 500)
    assert len(result) == 1000


class _NeverEqual:
    def __eq__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return 0


def test_writable_identity_check_rejects_a_never_equal_container(state: EvalState) -> None:
    obj = _NeverEqual()
    state.supplied[id(obj)] = obj
    with pytest.raises(RuleEvalPermissionError):
        __sb_writable__(obj)
