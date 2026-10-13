"""Smoke tests for CLI wiring without live LLM calls."""

from unittest.mock import MagicMock, patch

from crewai_demo.main import _normalize_chat_model_spec, main


def test_normalize_chat_model_colon_or_slash() -> None:
    assert _normalize_chat_model_spec("groq:llama-3.3-70b-versatile") == "groq/llama-3.3-70b-versatile"
    assert _normalize_chat_model_spec("openai/gpt-4o-mini") == "openai/gpt-4o-mini"
    assert _normalize_chat_model_spec("anthropic/claude-sonnet-4-20250514") == "anthropic/claude-sonnet-4-20250514"


@patch("crewai_demo.main.Crew")
@patch("crewai_demo.main.build_llm")
def test_main_kickoff_prints(mock_build_llm: MagicMock, mock_crew_cls: MagicMock) -> None:
    # Agent accepts ``llm`` as a model id string (no API call until kickoff).
    mock_build_llm.return_value = "openai/gpt-4o-mini"
    mock_crew = MagicMock()
    mock_result = MagicMock()
    mock_result.raw = "Task complete."
    mock_crew.kickoff.return_value = mock_result
    mock_crew_cls.return_value = mock_crew

    code = main(["--task", "Use tools to add 1 and 1 via evaluate_expression only."])

    assert code == 0
    mock_crew.kickoff.assert_called_once()
