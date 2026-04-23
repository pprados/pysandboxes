"""Smoke tests for run helpers (Agent mocked — no API keys)."""

from unittest.mock import MagicMock, patch

from strands.agent.agent_result import AgentResult
from strands.telemetry.metrics import EventLoopMetrics
from strands.types.content import Message

from strands_agents_demo.run import format_final_text, run_agent_task


def _fake_result(text: str) -> AgentResult:
    msg: Message = {"role": "assistant", "content": [{"text": text}]}
    return AgentResult(
        stop_reason="end_turn",
        message=msg,
        metrics=EventLoopMetrics(),
        state=None,
    )


def test_format_final_text() -> None:
    r = _fake_result("hello")
    assert format_final_text(r) == "hello"


@patch("strands_agents_demo.run.Agent")
def test_run_agent_task_invokes_agent(mock_agent_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_agent_cls.return_value = mock_inst
    mock_inst.return_value = _fake_result("done")

    model = MagicMock()
    out = run_agent_task(
        model,
        "task",
        system_prompt="sys",
        max_model_calls=5,
        verbose=False,
    )

    assert format_final_text(out) == "done"
    mock_agent_cls.assert_called_once()
    mock_inst.assert_called_once_with("task")
