# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes import learning, lifecycle
from pysandboxes.learning import LearnFileRule, add_learning_rule, is_learning_mode, set_learning_mode
from pysandboxes.lifecycle import enter, is_in_sandbox, leave
from pysandboxes.tools import set_is_in_sandbox


@pytest.fixture
def learning_state() -> Iterator[None]:
    mode, rules = learning._learning_mode, set(learning._learning)
    yield
    learning._learning_mode = mode
    learning._learning.clear()
    learning._learning.update(rules)


def test_the_contracts_are_armed_on_the_lifecycle() -> None:
    """Negative control: without a marker the contract tests below would pass on a plain function."""
    for func in (enter, leave, set_is_in_sandbox, set_learning_mode, add_learning_rule):
        assert hasattr(func, "__deal_contract")


@given(st.integers(1, 6))
def test_the_process_stays_in_the_sandbox_until_every_enter_is_undone(n: int) -> None:
    lifecycle._entered = 0
    for _ in range(n):
        enter()
        assert is_in_sandbox()
    for _ in range(n):
        assert is_in_sandbox()
        leave()
    assert not is_in_sandbox()


@given(st.lists(st.booleans(), max_size=12))
def test_set_is_in_sandbox_nests_like_enter_and_leave(values: list[bool]) -> None:
    lifecycle._entered = 0
    depth = 0
    for value in values:
        if not value and depth == 0:
            continue
        set_is_in_sandbox(value)
        depth += 1 if value else -1
        assert is_in_sandbox() == (depth > 0)
        assert lifecycle._entered == depth
    lifecycle._entered = 0


def test_an_unbalanced_leave_is_refused() -> None:
    lifecycle._entered = 0
    with pytest.raises(AssertionError):
        leave()
    lifecycle._entered = 0


def test_a_negative_counter_is_refused_too() -> None:
    lifecycle._entered = -1
    try:
        with pytest.raises(AssertionError):
            leave()
        assert lifecycle._entered == -1
    finally:
        lifecycle._entered = 0


def test_a_refused_leave_does_not_corrupt_the_counter() -> None:
    lifecycle._entered = 0
    try:
        with pytest.raises(AssertionError):
            leave()
        assert lifecycle._entered == 0
        enter()
        assert is_in_sandbox()
    finally:
        lifecycle._entered = 0


@pytest.mark.parametrize("mode", [True, False])
def test_the_learning_mode_reads_back_what_was_set(learning_state: None, mode: bool) -> None:
    set_learning_mode(mode)
    assert is_learning_mode() is mode


def test_a_rule_is_kept_once_in_learning_mode_and_dropped_otherwise(learning_state: None) -> None:
    rule = LearnFileRule(Path("/contract-test"), False)
    learning._learning.discard(rule)
    set_learning_mode(False)
    add_learning_rule(rule)
    assert rule not in learning._learning
    set_learning_mode(True)
    add_learning_rule(rule)
    add_learning_rule(rule)
    assert rule in learning._learning
    assert sum(r == rule for r in learning._learning) == 1
