"""CLI entry: load chat model from env, run tool-bound agent loop."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pysandboxes import sandboxes

from langchain_demo.chain import run_agent_loop
from langchain_demo.tools import evaluate_expression, fetch_webpage

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent page content or numeric results without calling the tools. "
    "evaluate_expression takes a single expression, not statements."
)

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, then use "
    "evaluate_expression to compute 2*(3+4), and report both results in one sentence."
)

DEFAULT_HINT = f"""LangChain agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _normalize_chat_model_spec(spec: str) -> str:
    """Normalize to ``provider:model`` for LangChain ``init_chat_model``.

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


def build_chat_model() -> BaseChatModel:
    """Instantiate a chat model from ``CHAT_MODEL`` (``provider:model`` or ``provider/model``)."""
    spec = _normalize_chat_model_spec(os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini"))
    return init_chat_model(spec)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LangChain tool-calling agent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument("--max-iterations", type=int, default=12, help="Cap on model+tool rounds.")
    p.add_argument("-v", "--verbose", action="store_true", help="Log agent turns and tool calls.")
    return p.parse_args(list(argv) if argv is not None else None)


def _answer(final: AIMessage) -> str:
    return (final.content or "").strip() or "(empty assistant content)"


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


def chat(
    llm: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    max_iterations: int,
) -> int:
    """Hold a conversation, carrying LangChain's own message list across turns.

    The sandbox is entered once, around the whole conversation. It has to stay
    armed for every turn: `@sandbox` needs a running daemon at call time, and a
    context manager opened per turn would pay the daemon's startup on each one.
    """
    messages: list[BaseMessage] = [SystemMessage(content=DEFAULT_SYSTEM)]
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        while True:
            line = _read_user_turn()
            if line is None:
                return 0
            if not line:
                continue
            messages.append(HumanMessage(content=line))
            try:
                # run_agent_loop appends the assistant and tool messages it
                # produces, so the history a turn leaves behind is the one the
                # next turn sends back to the model.
                final = run_agent_loop(llm, tools, messages, max_iterations=max_iterations)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            print(f"bot> {_answer(final)}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = [fetch_webpage, evaluate_expression]
    try:
        llm = build_chat_model()
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        return chat(llm, tools, max_iterations=args.max_iterations)

    messages: list[BaseMessage] = [
        SystemMessage(content=DEFAULT_SYSTEM),
        HumanMessage(content=args.task),
    ]
    try:
        # Partial mode: only the tools run in the sandbox. The context manager
        # has to wrap the loop that *calls* them -- @sandbox needs a running
        # daemon at call time, and the loop is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            final = run_agent_loop(
                llm,
                tools,
                messages,
                max_iterations=args.max_iterations,
            )
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1
    if not isinstance(final, AIMessage):
        print("Unexpected final message type.", file=sys.stderr)
        return 2
    print(_answer(final))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
