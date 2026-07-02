"""CLI: load model from env, build Pydantic AI ``Agent``, run with usage limits."""

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from pydantic_ai.usage import UsageLimits
from pysandboxes import sandboxes

from pydantic_ai_demo.agent_factory import build_agent

CONFIG = Path(__file__).parent.parent / ".py-sandboxes"

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, report how many "
    "words its title contains, then use evaluate_expression to compute that count squared. "
    "End with a one-sentence summary that includes both numbers."
)


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
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=15,
        help="Cap on model requests (Pydantic AI UsageLimits.request_limit; default 15).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log at INFO (framework may log steps).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    raw = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")
    model_spec = _normalize_chat_model_spec(raw)
    agent = build_agent(model_spec)
    usage_limits = UsageLimits(request_limit=max(1, args.max_iterations))

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
