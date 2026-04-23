"""Iteration cap hook."""

from unittest.mock import MagicMock

import pytest
from strands.hooks.events import BeforeInvocationEvent, BeforeModelCallEvent

from strands_agents_demo.hooks import MaxModelCallsHook


def test_max_model_calls_raises_after_limit() -> None:
    agent = MagicMock()
    hook = MaxModelCallsHook(2)
    hook._on_invocation_start(BeforeInvocationEvent(agent=agent, invocation_state={}, messages=None))
    hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))
    hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))
    with pytest.raises(RuntimeError, match="Exceeded max_model_calls"):
        hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))


def test_invocation_resets_counter() -> None:
    agent = MagicMock()
    hook = MaxModelCallsHook(1)
    hook._on_invocation_start(BeforeInvocationEvent(agent=agent, invocation_state={}, messages=None))
    hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))
    with pytest.raises(RuntimeError):
        hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))
    hook._on_invocation_start(BeforeInvocationEvent(agent=agent, invocation_state={}, messages=None))
    hook._before_model(BeforeModelCallEvent(agent=agent, invocation_state={}))
