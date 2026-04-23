"""Build a Pydantic AI ``Agent`` with ``fetch_webpage`` and ``execute_python`` tools."""

from pydantic_ai import Agent

from pydantic_ai_demo.tools import execute_python as execute_python_fn
from pydantic_ai_demo.tools import fetch_webpage as fetch_webpage_fn

DEFAULT_INSTRUCTIONS = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent HTML, titles, or numeric results without calling the tools. "
    "When you call execute_python, pass the exact text returned by fetch_webpage as your HTML "
    "string (assign it to a variable and parse that). "
    "When using re.search, check the match is not None before calling .group(); if there is no "
    "match, widen the pattern or inspect the HTML."
)


def build_agent(model_spec: str, *, instructions: str | None = None) -> Agent[None, str]:
    """Create an agent with web fetch and restricted Python execution tools.

    Tools are registered on this instance only; the model string selects the backend
    (see Pydantic AI docs for ``provider:model_id`` forms).
    """
    agent: Agent[None, str] = Agent(
        model_spec,
        output_type=str,
        instructions=instructions or DEFAULT_INSTRUCTIONS,
    )

    @agent.tool_plain
    def fetch_webpage(url: str) -> str:
        return fetch_webpage_fn(url)

    @agent.tool_plain
    def execute_python(code: str) -> str:
        return execute_python_fn(code)

    return agent
