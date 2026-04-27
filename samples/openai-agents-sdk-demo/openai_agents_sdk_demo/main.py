"""CLI: OpenAI Agents SDK ``Runner`` with ``fetch_webpage`` and ``execute_python``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Sequence

from agents import Agent, Runner, set_tracing_disabled
from dotenv import load_dotenv

from openai_agents_sdk_demo.model_config import normalize_chat_model_spec
from openai_agents_sdk_demo.tools import execute_python, fetch_webpage

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent HTML, titles, or numeric results without calling the tools. "
    "When you call execute_python, use the exact text returned by fetch_webpage as your HTML "
    "source. Parse it with the `re` module only (it is available without importing). "
    "Do not import or use bs4, BeautifulSoup, html.parser, lxml, or any third-party HTML library. "
    "If you embed the HTML in a Python string literal, use triple-single-quoted strings '''...''' "
    'rather than triple-double quotes """...""" — HTML often contains characters that break '
    "double-quoted triple-quoted literals. "
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


def _maybe_disable_tracing() -> None:
    """Avoid OpenAI trace upload 401s when no OpenAI key is configured."""
    if not os.environ.get("OPENAI_API_KEY"):
        set_tracing_disabled(True)


def _build_agent(model: str) -> Agent:
    return Agent(
        name="Tool demo",
        instructions=DEFAULT_SYSTEM,
        model=model,
        tools=[fetch_webpage, execute_python],
    )


async def run_agent_async(task: str, *, max_turns: int, model: str) -> str:
    agent = _build_agent(model)
    result = await Runner.run(agent, task, max_turns=max_turns)
    return (result.final_output or "").strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OpenAI Agents SDK tool-calling demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TURNS", "12")),
        help="Cap on agent turns (Runner max_turns).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log at INFO level.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)
    _maybe_disable_tracing()

    model = normalize_chat_model_spec(os.environ.get("CHAT_MODEL", ""))
    log = logging.getLogger(__name__)
    log.info("Using model: %s", model)

    try:
        text = asyncio.run(
            run_agent_async(args.task, max_turns=args.max_turns, model=model),
        )
    except Exception as e:
        log.error("Agent failed: %s", e, exc_info=True)
        return 1
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
