"""CLI: LiteLLM-backed model, ToolCallingAgent, default task requiring tools."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from pysandboxes import sandboxes
from smolagents import ToolCallingAgent
from smolagents.monitoring import LogLevel

from smolagents_demo.model_builder import build_model_from_env
from smolagents_demo.tools import evaluate_expression, fetch_webpage

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

DEFAULT_HINT = f"""smolagents agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def build_agent(*, max_steps: int, verbose: bool) -> ToolCallingAgent:
    """Construct ``ToolCallingAgent`` with fetch + Python tools and ``LiteLLMModel`` from env."""
    model = build_model_from_env()
    verbosity = LogLevel.DEBUG if verbose else LogLevel.ERROR
    return ToolCallingAgent(
        tools=[fetch_webpage, evaluate_expression],
        model=model,
        instructions=DEFAULT_SYSTEM,
        max_steps=max_steps,
        verbosity_level=verbosity,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="smolagents ToolCallingAgent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="Maximum agent steps (maps to MultiStepAgent max_steps).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Rich DEBUG logs from smolagents.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


def chat(agent: ToolCallingAgent, *, max_iterations: int) -> int:
    """Hold a conversation, carrying smolagents' own memory across turns.

    The sandbox is entered once, around the whole conversation. It has to stay
    armed for every turn: `@sandbox` needs a running daemon at call time, and a
    context manager opened per turn would pay the daemon's startup on each one.
    """
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        while True:
            line = _read_user_turn()
            if line is None:
                return 0
            if not line:
                continue
            try:
                # reset=False keeps the agent's own memory, so this turn's
                # answer builds on every earlier turn instead of starting over.
                final = agent.run(line, reset=False, max_steps=max_iterations)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            text = final if isinstance(final, str) else str(final)
            print(f"bot> {text or '(empty assistant content)'}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        agent = build_agent(max_steps=max(1, args.max_iterations), verbose=args.verbose)
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        return chat(agent, max_iterations=max(1, args.max_iterations))

    model_label = (os.environ.get("CHAT_MODEL") or "openai/gpt-4o-mini").strip()
    print(
        f"Running ToolCallingAgent (CHAT_MODEL={model_label!r}). "
        "Several LLM/tool steps may take a minute; use -v for DEBUG logs.",
        file=sys.stderr,
        flush=True,
    )
    try:
        # Partial mode: only the tool bodies run in the sandbox. The context
        # manager has to wrap the run that *calls* them -- @sandbox needs a
        # running daemon at call time, and agent.run() is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            final = agent.run(args.task, max_steps=max(1, args.max_iterations))
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1
    text = final if isinstance(final, str) else str(final)
    print(text or "(empty assistant content)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
