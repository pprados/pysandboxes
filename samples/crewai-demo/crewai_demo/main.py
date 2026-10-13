"""CLI: configurable LLM via env, CrewAI agent with tools and task kickoff."""

import argparse
import json
import logging
import os
import sys
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

DEFAULT_HINT = f"""CrewAI crew, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""

# A single task whose description is re-interpolated on every kickoff (see chat() below).
CHAT_TASK_DESCRIPTION = f"{DEFAULT_SYSTEM_GOAL} Complete the user's latest request fully.\n\nUser: {{user_turn}}"


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
        default=os.environ.get("AGENT_TASK"),
        help="Run a single task and exit. Omitted: start an interactive chat.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("AGENT_MAX_ITER", "12")),
        help="Cap on agent iterations for tool use (maps to Agent.max_iter).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose CrewAI and logging.")
    return p.parse_args(list(argv) if argv is not None else None)


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


def chat(agent: Agent, *, verbose: bool) -> int:
    """Hold a conversation, carrying history through CrewAI's own chat inputs.

    LangChain's agent takes a mutable list of ``BaseMessage`` objects that *is*
    the running conversation -- each call appends to it in place. ``Crew.kickoff()``
    has no such parameter: every call rebuilds the task from its (static)
    description, so the transcript has to be re-injected explicitly. CrewAI's own
    ``crewai chat`` CLI (crewai/cli/crew_chat.py) solves this the same way: it
    keeps a plain ``{"role", "content"}`` message list and passes it back in on
    every kickoff via ``inputs["crew_chat_messages"]`` --
    ``Task.interpolate_inputs_and_add_conversation_history`` recognizes that key
    and appends the transcript to the task description itself. Reusing one Task
    is safe because that method re-interpolates from the *original* description
    every time, so the transcript is never appended twice.

    The sandbox is entered once, around the whole conversation, for the same
    reason as the one-shot path below: ``@sandbox`` needs a running daemon at
    call time, and a context manager opened per turn would pay the daemon's
    startup on each one.
    """
    task = Task(
        description=CHAT_TASK_DESCRIPTION,
        expected_output="A direct answer to the user's latest message.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], verbose=verbose)
    messages: list[dict[str, str]] = []
    print(f"{DEFAULT_HINT}\n")
    with sandboxes(sandboxes_config=CONFIG):
        while True:
            line = _read_user_turn()
            if line is None:
                return 0
            if not line:
                continue
            inputs: dict[str, str] = {"user_turn": line}
            if messages:
                # Omitted on the first turn: an empty transcript is still
                # truthy as JSON ("[]"), which would make CrewAI append its
                # "review the conversation history" instruction for nothing.
                inputs["crew_chat_messages"] = json.dumps(messages)
            try:
                result = crew.kickoff(inputs=inputs)
            except Exception as e:
                print(f"bot> turn failed: {e}", file=sys.stderr)
                continue
            raw = getattr(result, "raw", None)
            answer = str(raw if raw is not None else result).strip()
            messages.append({"role": "user", "content": line})
            messages.append({"role": "assistant", "content": answer})
            print(f"bot> {answer}\n")


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    _configure_logging(args.verbose)

    tools = [fetch_webpage, evaluate_expression]
    try:
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
    except Exception as e:
        print(f"Cannot build the chat model: {e}", file=sys.stderr)
        print("Set CHAT_MODEL and the provider's API key (see README, or .env).", file=sys.stderr)
        return 2

    if args.task is None:
        return chat(agent, verbose=args.verbose)

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
