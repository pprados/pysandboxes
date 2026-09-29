"""CLI: load chat model from env, run AutoGen tool agent."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

import pysandboxes
from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from dotenv import load_dotenv

from autogen_demo.model_client import build_chat_completion_client
from autogen_demo.run import AGENT_NAME, final_assistant_text, run_agent_session

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent page content or numeric results without calling the tools."
)

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, report how many "
    "words its title contains, then use evaluate_expression to compute that count squared. "
    "End with a one-sentence summary that includes both numbers."
)

DEFAULT_HINT = f"""AutoGen agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _load_tools() -> Sequence:
    """The two tools the model is offered.

    Returns:
        Sequence of tool callables.
    """
    from autogen_demo.tools import evaluate_expression, fetch_webpage

    return [fetch_webpage, evaluate_expression]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoGen AgentChat tool demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-tool-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TOOL_ITERATIONS", "12")),
        help="Cap on tool-calling rounds inside the assistant (AutoGen max_tool_iterations).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Stream agent output to the console.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


async def chat(
    model_client: ChatCompletionClient,
    tools: Sequence,
    *,
    system_message: str,
    max_tool_iterations: int,
    verbose: bool,
) -> int:
    """Hold a conversation, letting the ``AssistantAgent`` carry its own history.

    One agent instance is built for the whole conversation and reused across turns:
    per its documented contract, it keeps its own model context between calls to
    ``run``, so only the new user line is passed in, never the accumulated history.
    """
    agent = AssistantAgent(
        name=AGENT_NAME,
        model_client=model_client,
        tools=list(tools),
        system_message=system_message,
        reflect_on_tool_use=True,
        model_client_stream=verbose,
        max_tool_iterations=max_tool_iterations,
    )
    print(f"{DEFAULT_HINT}\n")
    try:
        while True:
            # input() blocks; this runs inside pysandboxes.run's event loop.
            line = await asyncio.to_thread(_read_user_turn)
            if line is None:
                return 0
            if not line:
                continue
            try:
                result = await agent.run(task=line)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            print(f"bot> {final_assistant_text(result) or '(empty assistant content)'}\n")
    finally:
        await model_client.close()


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = _load_tools()
    try:
        model_client = build_chat_completion_client()
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        try:
            # Partial mode: only the tool bodies run in the sandbox. `pysandboxes.run()`
            # is the asynchronous entry point -- it arms the profile *and* binds the
            # sandbox loop, which `async with sandboxes(...)` alone does not do.
            return pysandboxes.run(
                chat(
                    model_client,
                    tools,
                    system_message=DEFAULT_SYSTEM,
                    max_tool_iterations=args.max_tool_iterations,
                    verbose=args.verbose,
                ),
                sandboxes_config=CONFIG,
            )
        except Exception as e:
            logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
            return 1

    async def _run() -> str:
        try:
            return await run_agent_session(
                model_client,
                task=args.task,
                system_message=DEFAULT_SYSTEM,
                max_tool_iterations=args.max_tool_iterations,
                verbose=args.verbose,
                tools=tools,
            )
        finally:
            await model_client.close()

    try:
        # Partial mode: only the tool bodies run in the sandbox. `pysandboxes.run()`
        # is the asynchronous entry point -- it arms the profile *and* binds the
        # sandbox loop, which `async with sandboxes(...)` alone does not do.
        text = pysandboxes.run(_run(), sandboxes_config=CONFIG)
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
