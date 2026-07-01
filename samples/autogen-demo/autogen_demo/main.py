"""CLI: load chat model from env, run AutoGen tool agent."""

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

import pysandboxes
from dotenv import load_dotenv

from autogen_demo.model_client import build_chat_completion_client
from autogen_demo.run import run_agent_session

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
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = _load_tools()
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
        # Partial mode: only the tool bodies run in the sandbox. `pysandboxes.run()`
        # is the asynchronous entry point -- it arms the profile *and* binds the
        # sandbox loop, which `async with sandboxes(...)` alone does not do.
        text = pysandboxes.run(_run(), config_path=CONFIG)
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
