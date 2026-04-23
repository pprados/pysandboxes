"""Tests for task result text extraction."""

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage

from autogen_demo.run import AGENT_NAME, final_assistant_text


def test_final_assistant_text_prefers_last_agent_message() -> None:
    result = TaskResult(
        messages=[
            TextMessage(source="user", content="hi"),
            TextMessage(source=AGENT_NAME, content="first"),
            TextMessage(source=AGENT_NAME, content="last answer"),
        ],
        stop_reason="stop",
    )
    assert final_assistant_text(result) == "last answer"
