"""Agent loop tests with mocked chat model."""

from unittest.mock import MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langchain_demo.chain import run_agent_loop
from langchain_demo.tools import execute_python, fetch_webpage


def test_run_agent_loop_tool_then_final() -> None:
    llm = MagicMock(spec=BaseChatModel)
    bound = MagicMock()
    llm.bind_tools.return_value = bound

    msg1 = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "execute_python",
                "args": {"code": "result = 40 + 2"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    msg2 = AIMessage(content="The computation yields 42.")
    bound.invoke.side_effect = [msg1, msg2]

    tools = [fetch_webpage, execute_python]
    messages: list = [SystemMessage(content="sys"), HumanMessage(content="user")]
    final = run_agent_loop(llm, tools, messages, max_iterations=5)

    assert isinstance(final, AIMessage)
    assert "42" in (final.content or "")
    assert bound.invoke.call_count == 2
    assert len(messages) == 5


def test_run_agent_loop_max_iterations() -> None:
    llm = MagicMock(spec=BaseChatModel)
    bound = MagicMock()
    llm.bind_tools.return_value = bound

    always_tools = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "execute_python",
                "args": {"code": "result = 1"},
                "id": "call_loop",
                "type": "tool_call",
            }
        ],
    )
    bound.invoke.side_effect = [always_tools, always_tools]

    tools = [fetch_webpage, execute_python]
    messages = [HumanMessage(content="x")]
    with pytest.raises(RuntimeError, match="Exceeded max_iterations"):
        run_agent_loop(llm, tools, messages, max_iterations=2)
