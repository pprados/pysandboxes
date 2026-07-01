"""Agent loop tests with mocked chat model."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pysandboxes import sandboxes

from langchain_demo.chain import run_agent_loop
from langchain_demo.tools import evaluate_expression, fetch_webpage

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"


def test_run_agent_loop_tool_then_final() -> None:
    llm = MagicMock(spec=BaseChatModel)
    bound = MagicMock()
    llm.bind_tools.return_value = bound

    msg1 = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "evaluate_expression",
                "args": {"expression": "40 + 2"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    msg2 = AIMessage(content="The computation yields 42.")
    bound.invoke.side_effect = [msg1, msg2]

    tools = [fetch_webpage, evaluate_expression]
    messages: list = [SystemMessage(content="sys"), HumanMessage(content="user")]
    # The loop really invokes the tool, and the tool's inner function carries
    # @sandbox, so a daemon has to be running -- exactly as main.py arranges.
    # This is where the D7 indirection is verified through the framework itself:
    # if @tool sat on the sandboxed function, the bridge could not resolve it.
    with sandboxes(sandboxes_config=CONFIG):
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
                "name": "evaluate_expression",
                "args": {"expression": "1"},
                "id": "call_loop",
                "type": "tool_call",
            }
        ],
    )
    bound.invoke.side_effect = [always_tools, always_tools]

    tools = [fetch_webpage, evaluate_expression]
    messages = [HumanMessage(content="x")]
    with sandboxes(sandboxes_config=CONFIG), pytest.raises(RuntimeError, match="Exceeded max_iterations"):
        run_agent_loop(llm, tools, messages, max_iterations=2)
