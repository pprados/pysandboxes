"""Unit tests for CLI helpers and agent wiring."""

from unittest.mock import MagicMock, patch

import pytest

from agno_demo.main import build_agent, normalize_chat_model_spec, parse_args


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("openai:gpt-4o-mini", "openai:gpt-4o-mini"),
        ("openai/gpt-4o-mini", "openai:gpt-4o-mini"),
        ("litellm/openai/gpt-4o", "litellm:openai/gpt-4o"),
    ],
)
def test_normalize_chat_model_spec(raw: str, expected: str) -> None:
    assert normalize_chat_model_spec(raw) == expected


def test_build_agent_sets_tool_limit() -> None:
    agent = build_agent(model_spec="openai:gpt-4o-mini", max_tool_calls=10)
    assert agent.tool_call_limit == 10
    assert agent.search_knowledge is False


def test_parse_args_defaults() -> None:
    ns = parse_args([])
    assert "google.com" in ns.task
    assert ns.max_tool_calls >= 1


@patch("agno_demo.main.Agent")
def test_main_prints_run_content(mock_agent_cls: MagicMock) -> None:
    from agno_demo.main import main

    mock_run = MagicMock()
    mock_run.content = "final answer"
    mock_agent_cls.return_value.run.return_value = mock_run

    code = main(["--task", "hello"])
    assert code == 0
    mock_agent_cls.assert_called_once()
    mock_agent_cls.return_value.run.assert_called_once_with("hello")
