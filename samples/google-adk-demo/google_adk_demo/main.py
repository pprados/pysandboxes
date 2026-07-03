"""CLI: load model from env, build ADK ``LlmAgent``, run tool-calling loop via Runner."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from pysandboxes import sandboxes

from google_adk_demo.model_builder import build_model_from_env
from google_adk_demo.run import build_runner, run_agent_once, run_agent_turn
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

DEFAULT_HINT = f"""Google ADK agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""

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
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="Cap on LLM calls per run (maps to RunConfig.max_llm_calls).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log tool calls and INFO.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


async def _run_chat(agent: LlmAgent, *, max_llm_calls: int) -> None:
    runner: Runner = build_runner(agent)
    # The Runner (and its ``async with``) wraps the whole conversation, opened once:
    # ADK's dispatch is async, so this is the natural place to hold it open, and
    # reusing user_id/session_id across turns is what makes the session -- ADK's own
    # history, not a hand-rolled list -- carry the conversation from turn to turn.
    async with runner:
        while True:
            line = await asyncio.to_thread(_read_user_turn)
            if line is None:
                return
            if not line:
                continue
            try:
                text = await run_agent_turn(runner, line, max_llm_calls=max_llm_calls)
            except Exception as e:
                # A refused tool is reported by the tool itself, inside the
                # conversation. Only a broken turn lands here, and it must not
                # end the chat.
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            print(f"bot> {text or '(empty assistant content)'}\n")


def chat(agent: LlmAgent, *, max_llm_calls: int) -> int:
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        asyncio.run(_run_chat(agent, max_llm_calls=max_llm_calls))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    try:
        agent = build_root_agent()
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        return chat(agent, max_llm_calls=max(1, args.max_iterations))

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
