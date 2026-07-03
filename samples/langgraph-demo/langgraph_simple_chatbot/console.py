# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Console chat for the LangGraph agent.

The conversation is carried by the graph itself: each turn sends the accumulated
messages into `ainvoke`, and the state the graph returns becomes the history the
next turn sends back. That is LangGraph's own idiom -- nothing here keeps a
parallel transcript.

The sandbox is not entered here. `cli.py` wraps this coroutine in
`pysandboxes.run()`, which arms the profile once for the whole conversation and
binds the sandbox loop; a context manager opened per turn would pay the daemon's
startup on every one.
"""

import asyncio

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage

from .agent import create_agent

load_dotenv()

DEFAULT_USER_TASK = (
    "Using the tools: fetch https://www.google.com with fetch_webpage, then use "
    "evaluate_expression to compute 2*(3+4), and report both results in one sentence."
)

DEFAULT_HINT = f"""LangGraph agent, tools confined by the sandbox. /quit or Ctrl-D to leave.
Try: {DEFAULT_USER_TASK}
Then ask for a host the profile does not allow, or for an expression that tries to
escape -- the tool answers with the rule that refused it."""


def _read_user_turn() -> str | None:
    """Read one chat line. ``None`` ends the conversation."""
    try:
        line = input("you> ").strip()
    except EOFError:
        print()
        return None
    return None if line in ("/quit", "/exit") else line


async def run_console_chat(model_name: str = "gpt-4o-mini", temperature: float = 0) -> None:
    """Hold a conversation with the agent until the user leaves.

    Args:
        model_name: The OpenAI model to use
        temperature: Temperature for the model
    """
    agent = create_agent(model_name=model_name, temperature=temperature)
    messages: list[BaseMessage] = []
    print(f"{DEFAULT_HINT}\n")

    while True:
        # input() blocks, and this coroutine shares its loop with the sandbox
        # transport: reading the prompt in a thread keeps that loop responsive.
        line = await asyncio.to_thread(_read_user_turn)
        if line is None:
            return
        if not line:
            continue
        messages.append(HumanMessage(content=line))
        try:
            result = await agent.ainvoke({"messages": messages})
        except Exception as e:
            # A refused tool is reported by the tool itself, inside the
            # conversation. Only a broken turn lands here, and it must not end
            # the chat.
            print(f"bot> turn failed: {e}\n")
            continue
        messages = list(result["messages"])
        print(f"bot> {messages[-1].content}\n")


def main() -> None:
    """Entry point for console chat."""
    asyncio.run(run_console_chat())


if __name__ == "__main__":
    main()
