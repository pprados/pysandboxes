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
    __sb_binop__,
    __sb_enter__,
    __sb_getattr__,
    __sb_iter__,
    __sb_leave__,
    __sb_tick__,
    _reset_regex_warnings,
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


def test_helpers_exposes_exactly_the_eight_names() -> None:
    assert set(HELPERS) == {
        "__sb_tick__",
        "__sb_enter__",
        "__sb_leave__",
        "__sb_func__",
        "__sb_getattr__",
        "__sb_binop__",
        "__sb_iter__",
        "__sb_format__",
    }
