# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from typing import cast

import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes.e import EvalInterrupted
from pysandboxes.eval_rules import EvalRules, parse_rules
from pysandboxes.eval_runtime import (
    EvalState,
    __sb_enter__,
    __sb_leave__,
    __sb_tick__,
    pop_state,
    push_state,
)
from pysandboxes.guard_eval import _interrupt
from pysandboxes.sb_types import ConfigLine

OPS = {"tick": __sb_tick__, "enter": __sb_enter__, "leave": __sb_leave__}


def _state(max_iterations: int, max_call_depth: int) -> EvalState:
    lines = [
        ConfigLine(f"eval-max-iterations={max_iterations}", Path("p"), 1),
        ConfigLine(f"eval-max-call-depth={max_call_depth}", Path("p"), 2),
    ]
    errors: list[tuple[str, Path, int]] = []
    profiles, _ = parse_rules(lines, errors)
    assert errors == []
    return EvalState(cast(EvalRules, profiles[""]))


def _run(op: str) -> bool:
    """Run one helper; tell whether it refused the evaluation."""
    try:
        OPS[op]()
    except EvalInterrupted:
        return True
    return False


@given(st.integers(1, 6), st.integers(1, 4), st.lists(st.sampled_from(sorted(OPS)), max_size=40))
def test_the_budget_invariants_hold_after_every_operation(
    max_iterations: int, max_call_depth: int, ops: list[str]
) -> None:
    state = _state(max_iterations, max_call_depth)
    push_state(state)
    try:
        was_interrupted = False
        previous = 0
        for op in ops:
            refused = _run(op)
            assert 0 <= state.depth <= max_call_depth
            assert 0 <= state.iterations <= max_iterations + 1
            assert state.iterations >= previous
            previous = state.iterations
            assert not state.interrupted or state.reason
            if was_interrupted:
                assert state.interrupted and (refused or op == "leave")
            was_interrupted = was_interrupted or state.interrupted
    finally:
        pop_state()


@given(st.integers(1, 6))
def test_the_iteration_budget_is_refused_exactly_when_it_runs_out(max_iterations: int) -> None:
    state = _state(max_iterations, 1)
    push_state(state)
    try:
        for _ in range(max_iterations):
            __sb_tick__()
        with pytest.raises(EvalInterrupted, match=f"eval-max-iterations={max_iterations}"):
            __sb_tick__()
        assert state.interrupted
    finally:
        pop_state()


def test_leaving_more_often_than_entering_never_goes_below_zero() -> None:
    state = _state(10, 2)
    push_state(state)
    try:
        for _ in range(5):
            __sb_leave__()
        assert state.depth == 0
    finally:
        pop_state()


def test_the_oracle_has_teeth() -> None:
    """Negative control: a state flagged interrupted without a reason breaks the invariant checked above."""
    state = _state(1, 1)
    state.interrupted = True
    assert state.interrupted and not state.reason


class _ObservedState(EvalState):
    """Records whether `interrupted` was already set at the moment `reason` is written."""

    __slots__ = ("seen", "_r")

    @property
    def reason(self) -> str:  # type: ignore[override]
        return self._r

    @reason.setter
    def reason(self, value: str) -> None:
        self.seen = self.interrupted
        self._r = value


def test_the_watchdog_publishes_the_reason_before_the_flag() -> None:
    state = _ObservedState(_state(1, 1).rules)
    _interrupt(state, 1.0)
    assert state.seen is False
