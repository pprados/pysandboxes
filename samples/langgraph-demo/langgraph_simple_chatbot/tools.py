# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tools exposed to the chat model via LangChain's tool API, driven by LangGraph.

Two tools, the same two every sample carries: one reaches the network, one
evaluates an expression the model supplies. What they demonstrate is that
pysandboxes can confine both without either of them being written defensively.

The tools are coroutines, which LangGraph's `ToolNode` awaits directly, and
`@sandbox` supports them. The shape is the indirection D7 of the design spec
asks for: `@tool` returns a StructuredTool, not a function, so what the model
calls is no longer callable by name -- and the sandbox bridge resolves a
function by ``module:qualname``, re-importing it inside the sandbox. So
`@sandbox` goes on a module-level ``_``-prefixed coroutine and `@tool` on a thin
wrapper delegating to it. Reversing the two makes the tool unresolvable in
partial mode.

The wrapper also converts errors. `@sandbox` re-raises, while a tool reports to
a model in text, and a refusal has to say which rule refused: httpx rewrites a
blocked connection into "All connection attempts failed", which any outage
produces too.
"""

import logging

import httpx
from langchain_core.tools import tool
from markdownify import markdownify as md
from pysandboxes import is_in_sandbox, sandbox, sandbox_denials

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0
_MAX_BODY_CHARS = 8000


def _explain(error: Exception) -> str:
    """Name the rule that refused the call, when one did."""
    denials = sandbox_denials(error)
    if not denials:
        return f"{type(error).__name__}: {error}"
    return f"{type(error).__name__}: {error} [refused by the sandbox: {'; '.join(denials)}]"


@sandbox
async def _fetch_webpage(url: str) -> str:
    """Fetch a webpage and return it as markdown."""
    assert is_in_sandbox()
    logger.info("Fetching webpage: %s", url)
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        text = md(response.text, heading_style="ATX", strip=["script", "style"])
    if len(text) > _MAX_BODY_CHARS:
        return text[:_MAX_BODY_CHARS] + "\n... [truncated]"
    return text


@sandbox
async def _evaluate_expression(expression: str) -> float:
    """Evaluate a mathematical expression and return the result.

    A plain eval() with an emptied ``__builtins__``, which is the naive
    hardening and is known not to hold: ``().__class__.__base__.__subclasses__()``
    still reaches Popen. That is the point. No expression is filtered here, so
    whatever blocks the escape is the sandbox and nothing else.
    """
    assert is_in_sandbox()
    logger.info("Evaluating: %s", expression)
    result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
    logger.info("Result: %s", result)
    return float(result)


@tool
async def fetch_webpage(url: str) -> str:
    """HTTP GET a URL and return the response body as markdown.

    Args:
        url: Absolute http(s) URL to fetch.

    Returns:
        The page as markdown, or a message naming the rule that refused it.
    """
    try:
        return await _fetch_webpage(url)
    except Exception as e:
        logger.warning("fetch_webpage refused for %s: %s", url, e)
        return f"Error fetching URL: {_explain(e)}"


@tool
async def evaluate_expression(expression: str) -> str:
    """Evaluate a mathematical expression and return the result.

    Args:
        expression: A Python expression, for instance "2 + 2" or "10 ** 2".

    Returns:
        The result as a string, or a message naming the rule that refused it.
    """
    try:
        return str(await _evaluate_expression(expression))
    except Exception as e:
        logger.warning("evaluate_expression refused for %r: %s", expression, e)
        return f"Error evaluating expression: {_explain(e)}"
