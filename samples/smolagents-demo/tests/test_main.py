"""CLI wiring tests (no real LLM)."""

from unittest.mock import MagicMock, patch

from smolagents_demo.main import build_agent, main


def test_build_agent_returns_tool_calling_agent() -> None:
    a = build_agent(max_steps=3, verbose=False)
    assert a.__class__.__name__ == "ToolCallingAgent"
    assert a.max_steps == 3


def test_main_success_mock_run() -> None:
    with patch("smolagents_demo.main.build_agent") as ba:
        mock_agent = MagicMock()
        mock_agent.run.return_value = "done"
        ba.return_value = mock_agent
        rc = main(["--task", "hello"])
    assert rc == 0
    mock_agent.run.assert_called_once()


def test_main_failure_returns_one() -> None:
    with patch("smolagents_demo.main.build_agent") as ba:
        mock_agent = MagicMock()
        mock_agent.run.side_effect = RuntimeError("boom")
        ba.return_value = mock_agent
        rc = main(["--task", "x"])
    assert rc == 1
