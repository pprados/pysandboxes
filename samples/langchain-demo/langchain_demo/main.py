"""CLI entry: load chat model from env, run tool-bound agent loop."""

import argparse
import logging
import os
import sys
from typing import Sequence

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langchain_demo.chain import run_agent_loop
from langchain_demo.tools import execute_python, fetch_webpage

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent HTML, titles, or numeric results without calling the tools. "
    "When you call execute_python, pass the exact text returned by fetch_webpage as your HTML "
    "string (assign it to a variable and parse that). "
    "When using re.search, check the match is not None before calling .group(); if there is no "
    "match, widen the pattern or inspect the HTML."
)

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, then use execute_python "
    "on the fetched HTML (not a made-up snippet) to extract the text inside the first "
    "<title>...</title> and report how many words that title contains (split on whitespace). "
    "End with a one-sentence summary that includes the word count."
)


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def build_chat_model() -> BaseChatModel:
    """Instantiate a chat model from ``CHAT_MODEL`` (``provider:model_id``)."""
    spec = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")
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

    tools = [fetch_webpage, execute_python]
    llm = build_chat_model()
    messages = [
        SystemMessage(content=DEFAULT_SYSTEM),
        HumanMessage(content=args.task),
    ]
    try:
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
