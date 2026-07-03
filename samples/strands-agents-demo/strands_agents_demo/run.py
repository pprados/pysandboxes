"""Construct the Strands agent and run one task."""

import logging
from pathlib import Path
from typing import Any

from pysandboxes import sandboxes
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.handlers.callback_handler import PrintingCallbackHandler, null_callback_handler
from strands.models.model import Model

from strands_agents_demo.hooks import MaxModelCallsHook
from strands_agents_demo.tools import evaluate_expression, fetch_webpage

logger = logging.getLogger(__name__)


CONFIG = Path(__file__).parent.parent / ".py-sandboxes"


def build_agent(
    model: Model,
    *,
    system_prompt: str,
    max_model_calls: int,
    verbose: bool,
) -> Agent:
    """Create an :class:`strands.Agent` with web + Python tools and an iteration cap."""
    cb: Any = PrintingCallbackHandler() if verbose else null_callback_handler
    hooks = [MaxModelCallsHook(max_model_calls)]
    return Agent(
        model=model,
        tools=[fetch_webpage, evaluate_expression],
        system_prompt=system_prompt,
        callback_handler=cb,
        hooks=hooks,
    )


def run_agent_task(
    model: Model,
    user_task: str,
    *,
    system_prompt: str,
    max_model_calls: int,
    verbose: bool,
) -> AgentResult:
    """Run a single user task through the Strands event loop (tools chosen by the model)."""
    agent = build_agent(
        model,
        system_prompt=system_prompt,
        max_model_calls=max_model_calls,
        verbose=verbose,
    )
    if verbose:
        logger.info("Running agent task (max_model_calls=%s)", max_model_calls)
    # Partial mode: only the tool bodies run in the sandbox. The context manager
    # has to wrap the call that *invokes* them -- @sandbox needs a running daemon
    # at call time, and the agent call is where the tool calls happen.
    with sandboxes(sandboxes_config=CONFIG):
        return agent(user_task)


def format_final_text(result: AgentResult) -> str:
    """Extract user-visible text from :class:`AgentResult`."""
    return str(result).strip()
