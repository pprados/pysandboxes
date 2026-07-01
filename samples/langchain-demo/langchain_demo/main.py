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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument("--max-iterations", type=int, default=12, help="Cap on model+tool rounds.")
    p.add_argument("-v", "--verbose", action="store_true", help="Log agent turns and tool calls.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = [fetch_webpage, evaluate_expression]
    llm = build_chat_model()
    messages = [
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
    text = (final.content or "").strip()
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
