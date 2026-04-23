"""Agent loop: model with bound tools until final assistant message or iteration cap."""

import logging
from typing import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def run_agent_loop(
    llm: BaseChatModel,
    tools: Sequence[BaseTool],
    messages: list[BaseMessage],
    *,
    max_iterations: int = 12,
) -> AIMessage:
    """Run bind_tools model in a loop until no tool calls or max_iterations.

    Tool execution is driven only by ``AIMessage.tool_calls`` from the model.
    """
    bound = llm.bind_tools(list(tools))
    by_name = {t.name: t for t in tools}
    for turn in range(1, max_iterations + 1):
        logger.info("Agent turn %s", turn)
        ai_msg = bound.invoke(messages)
        if not isinstance(ai_msg, AIMessage):
            raise TypeError(f"Expected AIMessage, got {type(ai_msg)}")
        messages.append(ai_msg)
        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if not tool_calls:
            return ai_msg
        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            tid = tc["id"]
            logger.info("Tool call: %s(%s)", name, args)
            tool = by_name.get(name)
            if tool is None:
                out = f"Unknown tool: {name}"
            else:
                out = tool.invoke(args)
            messages.append(ToolMessage(content=str(out), tool_call_id=tid))
    raise RuntimeError(f"Exceeded max_iterations={max_iterations}")
