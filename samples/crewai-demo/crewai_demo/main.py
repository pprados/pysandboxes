"""CLI: configurable LLM via env, CrewAI agent with tools and task kickoff."""

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from crewai import LLM, Agent, Crew, Task
from dotenv import load_dotenv
from pysandboxes import sandboxes

from crewai_demo.tools import evaluate_expression, fetch_webpage

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"

DEFAULT_SYSTEM_GOAL = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent page content or numeric results without calling the tools."
)

DEFAULT_BACKSTORY = "You are a careful assistant that follows tool-use rules and reports accurate results."

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, report how many "
    "words its title contains, then use evaluate_expression to compute that count squared. "
    "End with a one-sentence summary that includes both numbers."
)


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _normalize_chat_model_spec(spec: str) -> str:
    """Normalize to ``provider/model`` for CrewAI (LiteLLM-style ids).

    - Already slash-separated: returned unchanged (including ``a/b/c``).
    - Single ``provider:model`` with no ``/``: converted to ``provider/model``.
    - Multiple ``:`` (e.g. URLs): returned unchanged.
    """
    if "/" in spec or spec.count(":") != 1:
        return spec
    left, right = spec.split(":", 1)
    if left and right and not left.lower().startswith("http"):
        return f"{left}/{right}"
    return spec


def build_llm() -> LLM:
    """Build ``LLM`` from ``CHAT_MODEL`` (``provider/model`` or ``provider:model``)."""
    spec = _normalize_chat_model_spec(os.environ.get("CHAT_MODEL", "openai/gpt-4o-mini"))
    return LLM(model=spec)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CrewAI tool-using agent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_ITER", "12")),
        help="Cap on agent iterations for tool use (maps to Agent.max_iter).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose CrewAI and logging.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = [fetch_webpage, evaluate_expression]
    llm = build_llm()

    agent = Agent(
        role="Tool-using analyst",
        goal=f"{DEFAULT_SYSTEM_GOAL} Complete the user task fully.",
        backstory=DEFAULT_BACKSTORY,
        tools=tools,
        llm=llm,
        verbose=args.verbose,
        allow_delegation=False,
        max_iter=args.max_iterations,
    )

    task = Task(
        description=args.task,
        expected_output=(
            "A clear answer that reflects the real fetch_webpage content and the "
            "evaluate_expression result, including both numbers."
        ),
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=args.verbose,
    )

    try:
        # Partial mode: only the tool bodies run in the sandbox. The context
        # manager has to wrap the kickoff that *calls* them -- @sandbox needs a
        # running daemon at call time, and the crew is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            result = crew.kickoff()
    except Exception as e:
        logging.getLogger(__name__).error("Crew failed: %s", e, exc_info=True)
        return 1

    raw = getattr(result, "raw", None)
    if raw is not None:
        print(str(raw).strip())
    else:
        print(str(result).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
