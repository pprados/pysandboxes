"""CLI: load chat model from env, run AutoGen tool agent."""

import argparse
import asyncio
import logging
import os
from typing import Sequence

from dotenv import load_dotenv

from autogen_demo.model_client import build_chat_completion_client
from autogen_demo.run import run_agent_session

DEFAULT_SYSTEM = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent HTML, titles, or numeric results without calling the tools. "
    "When you call execute_python with HTML from fetch_webpage, assign it using a variable and "
    "triple-quoted strings (e.g. html = \"\"\"...\"\"\" or html = '''...''') so embedded quotes "
    "and newlines do not cause SyntaxError; never put a full HTML document inside a single-line "
    '"..." literal. '
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


def _load_tools(use_sandbox: bool, use_annotated: bool) -> Sequence:
    """Load tools based on sandbox and annotation flags.

    Returns:
        Sequence of tool callables.
    """
    if use_sandbox and use_annotated:
        raise ValueError("Cannot use both --use-python-sb and --annotated-tools together yet.")

    if use_sandbox:
        from autogen_demo.tools_sandbox import execute_python, fetch_webpage
    elif use_annotated:
        from autogen_demo.tools_annotated import execute_python, fetch_webpage
    else:
        from autogen_demo.tools import execute_python, fetch_webpage

    return [fetch_webpage, execute_python]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AutoGen AgentChat tool demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-tool-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TOOL_ITERATIONS", "12")),
        help="Cap on tool-calling rounds inside the assistant (AutoGen max_tool_iterations).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Stream agent output to the console.")
    p.add_argument(
        "--use-python-sb",
        action="store_true",
        help="Run execute_python inside python-sb OS sandbox (requires python-sb installed).",
    )
    p.add_argument(
        "--annotated-tools",
        action="store_true",
        help="Use tools with JSON Schema annotations for better model type awareness.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        tools = _load_tools(args.use_python_sb, args.annotated_tools)
    except ValueError as e:
        logging.getLogger(__name__).error("%s", e)
        return 1

    try:
        model_client = build_chat_completion_client()
    except ValueError as e:
        logging.getLogger(__name__).error("%s", e)
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
        text = asyncio.run(_run())
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
