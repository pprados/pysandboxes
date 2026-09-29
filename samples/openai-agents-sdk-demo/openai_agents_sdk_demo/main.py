"""CLI: OpenAI Agents SDK ``Runner`` with ``fetch_webpage`` and ``evaluate_expression``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

import pysandboxes
from agents import Agent, Runner, TResponseInputItem, set_tracing_disabled
from dotenv import load_dotenv

from openai_agents_sdk_demo.model_config import normalize_chat_model_spec
from openai_agents_sdk_demo.tools import evaluate_expression, fetch_webpage

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

DEFAULT_HINT = f"""OpenAI Agents SDK agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _maybe_disable_tracing() -> None:
    """Avoid OpenAI trace upload 401s when no OpenAI key is configured."""
    if not os.environ.get("OPENAI_API_KEY"):
        set_tracing_disabled(True)


def _build_agent(model: str) -> Agent:
    return Agent(
        name="Tool demo",
        instructions=DEFAULT_SYSTEM,
        model=model,
        tools=[fetch_webpage, evaluate_expression],
    )


async def run_agent_async(task: str, *, max_turns: int, model: str) -> str:
    agent = _build_agent(model)
    result = await Runner.run(agent, task, max_turns=max_turns)
    return (result.final_output or "").strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OpenAI Agents SDK tool-calling demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TURNS", "12")),
        help="Cap on agent turns (Runner max_turns).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log at INFO level.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


async def chat(agent: Agent, *, max_turns: int) -> int:
    """Hold a conversation, carrying the Agents SDK's own input-item history across turns.

    The sandbox is entered once, around the whole conversation. It has to stay
    armed for every turn: `@sandbox` needs a running daemon at call time, and a
    context manager opened per turn would pay the daemon's startup on each one.
    """
    print(f"{DEFAULT_HINT}\n")
    history: list[TResponseInputItem] = []
    while True:
        # input() is blocking; run it off the event loop pysandboxes.run() owns.
        line = await asyncio.to_thread(_read_user_turn)
        if line is None:
            return 0
        if not line:
            continue
        history.append({"role": "user", "content": line})
        try:
            result = await Runner.run(agent, history, max_turns=max_turns)
        except Exception as e:
            # A refused tool is reported by the tool itself, inside the
            # conversation. Only a broken turn lands here, and it must not
            # end the chat.
            print(f"bot> turn failed: {e}", file=sys.stderr)
            continue
        # to_input_list() replays this run as input items, so the history a
        # turn leaves behind is the one the next turn sends back to the model.
        history = result.to_input_list()
        print(f"bot> {(result.final_output or '').strip() or '(empty assistant content)'}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)
    _maybe_disable_tracing()

    model = normalize_chat_model_spec(os.environ.get("CHAT_MODEL", ""))
    log = logging.getLogger(__name__)
    log.info("Using model: %s", model)

    if args.task is None:
        try:
            agent = _build_agent(model)
        except Exception as e:
            print(f"Cannot build the chat model: {e}", file=sys.stderr)
            print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
            return 2
        # Same asynchronous entry point as the one-shot path below: it arms the
        # profile *and* binds the sandbox loop for the whole conversation.
        return pysandboxes.run(chat(agent, max_turns=args.max_turns), sandboxes_config=CONFIG)

    try:
        # Partial mode: only the tool bodies run in the sandbox. `pysandboxes.run()`
        # is the asynchronous entry point -- it arms the profile *and* binds the
        # sandbox loop, which `async with sandboxes(...)` alone does not do.
        text = pysandboxes.run(
            run_agent_async(args.task, max_turns=args.max_turns, model=model),
            sandboxes_config=CONFIG,
        )
    except Exception as e:
        log.error("Agent failed: %s", e, exc_info=True)
        return 1
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
