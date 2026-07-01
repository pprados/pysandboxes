"""CLI: Agno Agent with fetch + Python tools (model string from env)."""

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from agno.agent import Agent
from dotenv import load_dotenv
from pysandboxes import sandboxes

from agno_demo.tools import evaluate_expression, fetch_webpage

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


def normalize_chat_model_spec(spec: str) -> str:
    """Normalize to ``provider:model_id`` for Agno ``Agent(model=...)``.

    ``provider:model`` is passed through. A single ``provider/model`` (no ``:``) becomes
    ``provider:model``; the model id may still contain ``/`` after the first colon.
    """
    if ":" in spec:
        return spec
    if "/" not in spec:
        return spec
    left, right = spec.split("/", 1)
    if left and right and not left.lower().startswith("http"):
        return f"{left}:{right}"
    return spec


def build_agent(
    *,
    model_spec: str,
    max_tool_calls: int,
) -> Agent:
    """Agent with tools; ``search_knowledge`` disabled so only our tools are offered."""
    return Agent(
        model=model_spec,
        tools=[fetch_webpage, evaluate_expression],
        system_message=DEFAULT_SYSTEM,
        search_knowledge=False,
        tool_call_limit=max_tool_calls,
        markdown=False,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Agno tool-calling agent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-tool-calls",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TOOL_CALLS", "32")),
        help="Cap on tool invocations per run (maps to Agent.tool_call_limit).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    raw = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")
    model_spec = normalize_chat_model_spec(raw)

    agent = build_agent(model_spec=model_spec, max_tool_calls=args.max_tool_calls)
    try:
        # Partial mode: only the tool bodies run in the sandbox. The context
        # manager has to wrap the run that *calls* them -- @sandbox needs a
        # running daemon at call time, and agent.run() is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            run_output = agent.run(args.task)
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        return 1

    content = getattr(run_output, "content", None)
    text = (content if isinstance(content, str) else str(content or "")).strip()
    print(text or "(empty assistant content)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
