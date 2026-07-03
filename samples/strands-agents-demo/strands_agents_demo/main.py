"""CLI: Strands Agents tool-calling demo (console)."""

import argparse
import logging
import os
import sys
from typing import Sequence

from dotenv import load_dotenv
from pysandboxes import sandboxes
from strands.models.model import Model

from strands_agents_demo.model_factory import build_chat_model
from strands_agents_demo.run import CONFIG, build_agent, format_final_text, run_agent_task

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent page content or numeric results without calling the tools."
)

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, report how many "
    "words its title contains, then use evaluate_expression to compute that count squared. "
    "End with a one-sentence summary that includes both numbers."
)

DEFAULT_HINT = f"""Strands agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strands Agents tool-calling demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_ITERATIONS", "12")),
        help="Cap on model invocations per invocation (maps to Strands event-loop rounds).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log INFO and stream tool names to stdout.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


def chat(model: Model, *, system_prompt: str, max_model_calls: int, verbose: bool) -> int:
    """Hold a conversation, letting the Strands Agent carry its own message history.

    Reusing one Agent instance across turns means `agent.messages` accumulates the
    conversation, so that -- not a hand-rolled list -- is what each turn sends back
    to the model. The sandbox is entered once, around the whole conversation: it has
    to stay armed for every turn: `@sandbox` needs a running daemon at call time, and
    a context manager opened per turn would pay the daemon's startup on each one.
    """
    agent = build_agent(model, system_prompt=system_prompt, max_model_calls=max_model_calls, verbose=verbose)
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        while True:
            line = _read_user_turn()
            if line is None:
                return 0
            if not line:
                continue
            try:
                result = agent(line)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            print(f"bot> {format_final_text(result)}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        model = build_chat_model()
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        return chat(model, system_prompt=DEFAULT_SYSTEM, max_model_calls=args.max_iterations, verbose=args.verbose)

    try:
        result = run_agent_task(
            model,
            args.task,
            system_prompt=DEFAULT_SYSTEM,
            max_model_calls=args.max_iterations,
            verbose=args.verbose,
        )
    except RuntimeError as e:
        logging.getLogger(__name__).error("%s", e)
        return 2
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1

    text = format_final_text(result)
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
