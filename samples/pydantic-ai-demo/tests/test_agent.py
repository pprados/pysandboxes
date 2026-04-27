"""Agent tests with TestModel (no real LLM)."""

from collections.abc import Iterator

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

from pydantic_ai_demo.agent_factory import build_agent

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _block_real_model_requests() -> Iterator[None]:
    models.ALLOW_MODEL_REQUESTS = False
    yield
    models.ALLOW_MODEL_REQUESTS = True


async def test_run_async_with_test_model_completes() -> None:
    agent = build_agent("openai:gpt-4o-mini")
    with agent.override(model=TestModel()):
        result = await agent.run("ping", usage_limits=UsageLimits(request_limit=5))
    assert result.output is not None


def test_run_sync_with_test_model_completes() -> None:
    agent = build_agent("openai:gpt-4o-mini")
    with agent.override(model=TestModel()):
        result = agent.run_sync("ping", usage_limits=UsageLimits(request_limit=5))
    assert result.output is not None
