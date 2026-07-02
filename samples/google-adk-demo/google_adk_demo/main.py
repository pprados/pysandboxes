"""CLI: load model from env, build ADK ``LlmAgent``, run tool-calling loop via Runner."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from pysandboxes import sandboxes

from google_adk_demo.model_builder import build_model_from_env
from google_adk_demo.run import run_agent_once
from google_adk_demo.tools import evaluate_expression, fetch_webpage

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

AGENT_NAME = "demo_agent"

_TOOL_USE_FAILED_HINT = (
    "If you use Groq (or similar) via LiteLLM and see tool_use_failed / "
    "'not in request.tools', the model likely emitted non–OpenAI-style tool syntax. "
    "Use native Gemini for this demo: CHAT_MODEL=gemini-2.0-flash and GOOGLE_API_KEY."
)


def _log_hint_for_tool_backend_error(exc: BaseException) -> None:
    """After a failed run, log once if the exception matches known LiteLLM/Groq tool errors."""
    text = f"{type(exc).__name__}: {exc!s}"
    if "tool_use_failed" not in text and "was not in request.tools" not in text:
        return
    logging.getLogger(__name__).warning(_TOOL_USE_FAILED_HINT)


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def build_root_agent() -> LlmAgent:
    """Construct the root ``LlmAgent`` with tools and model from ``CHAT_MODEL``."""
    model = build_model_from_env()
    return LlmAgent(
        model=model,
        name=AGENT_NAME,
        instruction=DEFAULT_SYSTEM,
        tools=[fetch_webpage, evaluate_expression],
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Google ADK tool-calling agent demo (console).")
    p.add_argument(
        "--task",
        default=os.environ.get("AGENT_TASK", DEFAULT_USER_TASK),
        help="User task (must require tools; default uses https://www.google.com )",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="Cap on LLM calls per run (maps to RunConfig.max_llm_calls).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log tool calls and INFO.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    agent = build_root_agent()
    model_label = (os.environ.get("CHAT_MODEL") or "gemini-2.0-flash").strip()
    print(
        f"Running agent (CHAT_MODEL={model_label!r}). Several LLM/tool steps may take a minute; use -v for INFO logs.",
        file=sys.stderr,
        flush=True,
    )
    try:
        # Partial mode: only the tool bodies run in the sandbox. The context
        # manager has to wrap the run that *calls* them -- @sandbox needs a
        # running daemon at call time, and the runner is where the calls happen.
        with sandboxes(sandboxes_config=CONFIG):
            text = run_agent_once(
                agent,
                args.task,
                max_llm_calls=max(1, args.max_iterations),
            )
    except Exception as e:
        logging.getLogger(__name__).error("Agent failed: %s", e, exc_info=True)
        _log_hint_for_tool_backend_error(e)
        return 1
    print(text or "(empty assistant content)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
