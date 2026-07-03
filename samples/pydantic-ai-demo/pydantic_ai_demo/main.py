"""CLI: load model from env, build Pydantic AI ``Agent``, run with usage limits."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import UsageLimits
from pysandboxes import sandboxes

from pydantic_ai_demo.agent_factory import build_agent

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, report how many "
    "words its title contains, then use evaluate_expression to compute that count squared. "
    "End with a one-sentence summary that includes both numbers."
)

DEFAULT_HINT = f"""Pydantic AI agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _normalize_chat_model_spec(spec: str) -> str:
    """Normalize to ``provider:model_id`` for Pydantic AI model strings.

    - Already contains ``:``: returned unchanged (model id may include ``/`` after it).
    - Slash-only form ``provider/model``: first ``/`` becomes ``:`` (not treated as URL).
    """
    if ":" in spec:
        return spec
    if "/" not in spec:
        return spec
    left, right = spec.split("/", 1)
    if left and right and not left.lower().startswith("http"):
        return f"{left}:{right}"
    return spec


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pydantic AI tool-calling agent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=15,
        help="Cap on model requests (Pydantic AI UsageLimits.request_limit; default 15).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log at INFO (framework may log steps).")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


def chat(agent: Agent[None, str], *, usage_limits: UsageLimits) -> int:
    """Hold a conversation, carrying Pydantic AI's own message history across turns.

    The sandbox is entered once, around the whole conversation. It has to stay
    armed for every turn: `@sandbox` needs a running daemon at call time, and a
    context manager opened per turn would pay the daemon's startup on each one.
    """
    history: list[ModelMessage] = []
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        while True:
            line = _read_user_turn()
            if line is None:
                return 0
            if not line:
                continue
            try:
                # message_history carries the conversation; all_messages() below
                # returns it extended with this turn's request and response.
                result = agent.run_sync(line, message_history=history, usage_limits=usage_limits)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            history = result.all_messages()
            print(f"bot> {(result.output or '').strip() or '(empty assistant content)'}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    raw = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")
    model_spec = _normalize_chat_model_spec(raw)
    try:
        agent = build_agent(model_spec)
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2
    usage_limits = UsageLimits(request_limit=max(1, args.max_iterations))

    if args.task is None:
        return chat(agent, usage_limits=usage_limits)

    try:
        # Partial mode: only the tool bodies run in the sandbox. The context
        # manager has to wrap the run that *calls* them -- @sandbox needs a
        # running daemon at call time, and run_sync() is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            result = agent.run_sync(args.task, usage_limits=usage_limits)
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1

    text = (result.output or "").strip() if hasattr(result, "output") else str(result).strip()
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
