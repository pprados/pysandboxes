"""CLI: Strands Agents tool-calling demo (console)."""

import argparse
import logging
import os
from typing import Sequence

from dotenv import load_dotenv

from strands_agents_demo.model_factory import build_chat_model
from strands_agents_demo.run import format_final_text, run_agent_task

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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strands Agents tool-calling demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_ITERATIONS", "12")),
        help="Cap on model invocations per invocation (maps to Strands event-loop rounds).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log INFO and stream tool names to stdout.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        model = build_chat_model()
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
