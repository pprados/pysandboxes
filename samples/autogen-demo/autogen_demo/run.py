"""Run an AutoGen AssistantAgent with tools until completion."""

import json
import logging
import os
import time
from typing import Any, Sequence

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, TextMessage
from autogen_agentchat.ui import Console
from autogen_core.models import ChatCompletionClient

logger = logging.getLogger(__name__)

AGENT_NAME = "tool_assistant"

# region agent log
_RUN_DEBUG_LOG = "/home/philippe-prados/workspace/pysandboxes/.cursor/debug-12736d.log"


def _run_dbg(hypothesis_id: str, message: str, data: dict[str, Any], *, run_id: str | None = None) -> None:
    rid = run_id if run_id is not None else os.environ.get("AGENT_DEBUG_RUN_ID", "pre-fix")
    payload = {
        "sessionId": "12736d",
        "runId": rid,
        "hypothesisId": hypothesis_id,
        "location": "autogen_demo/run.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_RUN_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# endregion


def final_assistant_text(result: TaskResult, source: str = AGENT_NAME) -> str:
    """Last text message content from the named agent in the task result."""
    for msg in reversed(result.messages):
        if isinstance(msg, TextMessage) and msg.source == source:
            return (msg.content or "").strip()
    return ""


async def run_agent_session(
    model_client: ChatCompletionClient,
    *,
    task: str,
    system_message: str,
    max_tool_iterations: int,
    verbose: bool,
    tools: Sequence | None = None,
) -> str:
    """Run ``AssistantAgent`` with provided tools; return final assistant text.

    Args:
        tools: Sequence of tool callables. If None, imports default tools from autogen_demo.tools.
    """
    if tools is None:
        from autogen_demo.tools import evaluate_expression, fetch_webpage

        tools = [fetch_webpage, evaluate_expression]
    agent = AssistantAgent(
        name=AGENT_NAME,
        model_client=model_client,
        tools=list(tools),
        system_message=system_message,
        reflect_on_tool_use=True,
        model_client_stream=verbose,
        max_tool_iterations=max_tool_iterations,
    )
    stream = agent.run_stream(task=task)
    if verbose:
        last = await Console(stream, output_stats=False)
        if isinstance(last, TaskResult):
            return final_assistant_text(last) or "(empty assistant content)"
        return (last.chat_message.to_text() if hasattr(last, "chat_message") else str(last)).strip()

    last_result: TaskResult | None = None
    stream_msg_count = 0
    stream_types: list[str] = []
    async for message in stream:
        stream_msg_count += 1
        stream_types.append(type(message).__name__)
        if stream_msg_count <= 12:
            _run_dbg("H4", "stream_message", {"i": stream_msg_count, "type": type(message).__name__})
        if isinstance(message, TaskResult):
            last_result = message
        elif isinstance(message, (BaseAgentEvent, BaseChatMessage)):
            logger.debug("stream event: %s", type(message).__name__)
    # region agent log
    _run_dbg(
        "H4",
        "stream_done",
        {
            "stream_msg_count": stream_msg_count,
            "stop_reason": getattr(last_result, "stop_reason", None),
            "type_summary": {t: stream_types.count(t) for t in sorted(set(stream_types))},
        },
    )
    # endregion
    if last_result is None:
        return "(no task result)"
    return final_assistant_text(last_result) or "(empty assistant content)"
