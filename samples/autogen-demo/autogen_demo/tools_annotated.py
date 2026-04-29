"""Tools with JSON Schema annotations for better model type awareness.

Same as tools.py but with metadata for model introspection.
Expose via `--annotated-tools` flag.
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from autogen_demo.tools import _execute_python_sync, _DEFAULT_TIMEOUT, _MAX_BODY_CHARS

logger = logging.getLogger(__name__)


class ToolMetadata:
    """Wrapper that attaches JSON Schema metadata to async functions."""

    def __init__(
        self,
        func: Any,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ):
        self.func = func
        self.name = name
        self.description = description
        self.parameters = parameters
        self.__doc__ = f"{description}\n\nParameters: {json.dumps(parameters, indent=2)}"

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return await self.func(*args, **kwargs)


# JSON Schema for fetch_webpage parameter
_FETCH_WEBPAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "Absolute http(s) URL to fetch. Must start with http:// or https://.",
            "pattern": "^https?://",
        },
    },
    "required": ["url"],
}

# JSON Schema for execute_python parameter
_EXECUTE_PYTHON_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": (
                "Python source to execute. "
                "Use print() for output or assign to `result` for a return value. "
                "Allowed imports: re, math, json, itertools, functools, collections, operator, string. "
                "re module is always available without importing."
            ),
        },
    },
    "required": ["code"],
}


async def _fetch_webpage_impl(url: str) -> str:
    """HTTP GET a URL and return response body as text (truncated for large pages).

    Args:
        url: Absolute http(s) URL to fetch.

    Returns:
        Response body text, or an error string.
    """
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
    except Exception as e:
        logger.warning("fetch_webpage failed for %s: %s", url, e, exc_info=True)
        return f"Error fetching URL: {type(e).__name__}: {e}"
    if len(text) > _MAX_BODY_CHARS:
        return text[:_MAX_BODY_CHARS] + "\n... [truncated]"
    return text


async def _execute_python_impl(code: str) -> str:
    """Run Python code in a restricted namespace (demo only — not an OS sandbox).

    Use print() for output, or assign to the variable ``result`` for a return value.
    For ``re.search`` / ``re.match``, verify the match is not ``None`` before ``.group()``.

    Args:
        code: Python source to execute.

    Returns:
        Captured printed output, ``result`` value, or an error string.
    """
    print(f"EXEC PYTHON\n{code}")
    return await asyncio.to_thread(_execute_python_sync, code)


# Annotated tool instances
fetch_webpage = ToolMetadata(
    _fetch_webpage_impl,
    name="fetch_webpage",
    description="HTTP GET a URL and return response body as text (truncated for large pages).",
    parameters=_FETCH_WEBPAGE_SCHEMA,
)

execute_python = ToolMetadata(
    _execute_python_impl,
    name="execute_python",
    description="Run Python code in a restricted namespace. Use print() for output or assign result.",
    parameters=_EXECUTE_PYTHON_SCHEMA,
)


def get_tool_schemas() -> dict[str, dict[str, Any]]:
    """Return mapping of tool name → JSON Schema for model visibility."""
    return {
        "fetch_webpage": {
            "type": "function",
            "function": {
                "name": "fetch_webpage",
                "description": fetch_webpage.description,
                "parameters": _FETCH_WEBPAGE_SCHEMA,
            },
        },
        "execute_python": {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": execute_python.description,
                "parameters": _EXECUTE_PYTHON_SCHEMA,
            },
        },
    }
