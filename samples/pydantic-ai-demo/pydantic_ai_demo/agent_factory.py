"""Build a Pydantic AI ``Agent`` with ``fetch_webpage`` and ``evaluate_expression`` tools."""

from pydantic_ai import Agent

from pydantic_ai_demo.tools import evaluate_expression as evaluate_expression_fn
from pydantic_ai_demo.tools import fetch_webpage as fetch_webpage_fn

DEFAULT_INSTRUCTIONS = (
    "You must use the provided tools for any live webpage content or any computation. "
    "Do not invent page content or numeric results without calling the tools."
)


def build_agent(model_spec: str, *, instructions: str | None = None) -> Agent[None, str]:
    """Create an agent with the fetch and expression tools.

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
    def evaluate_expression(expression: str) -> str:
        return evaluate_expression_fn(expression)

    return agent
