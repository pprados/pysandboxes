"""Execute Python inside python-sb OS sandbox.

Use this module when launching with --use-python-sb flag.
execute_python() runs code in an isolated container, not just a restricted namespace.
"""

import asyncio
import io
import logging
from typing import Any

import httpx

try:
    from python_sb import sandbox
except ImportError:
    sandbox = None  # type: ignore

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0
_MAX_BODY_CHARS = 8000


async def fetch_webpage(url: str) -> str:
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


def _execute_python_in_sandbox(code: str) -> str:
    """Run Python inside python-sb container."""
    if sandbox is None:
        raise RuntimeError(
            "python-sb not installed. Run: cd samples/autogen-demo && uv pip install python-sb"
        )

    buf = io.StringIO()

    def safe_print(*args: object, **kwargs: Any) -> None:
        print(*args, file=buf, **kwargs)

    safe_builtins = {
        "print": safe_print,
        "len": len,
        "range": range,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "enumerate": enumerate,
        "zip": zip,
    }

    g: dict[str, Any] = {"__builtins__": safe_builtins}
    local_ns: dict[str, Any] = {}

    try:
        compiled = compile(code, "<execute_python>", "exec")
    except SyntaxError as e:
        logger.warning("execute_python sandbox failed: %s: %s", type(e).__name__, e)
        base = f"Error: {type(e).__name__}: {e}"
        if "unterminated string" in str(e).lower() or "invalid syntax" in str(e).lower():
            return (
                base + " Hint: for HTML from fetch_webpage, assign it with triple-quoted strings "
                '(html = """...""" or \'\'\'...\'\'\'), not a single "..." line with raw HTML inside.'
            )
        return base
    except Exception as e:
        logger.warning("execute_python sandbox failed: %s: %s", type(e).__name__, e)
        return f"Error: {type(e).__name__}: {e}"

    try:
        # Run inside sandbox context
        with sandbox():
            exec(compiled, g, local_ns)
    except Exception as e:
        logger.warning("execute_python sandbox exec failed: %s: %s", type(e).__name__, e)
        return f"Error: {type(e).__name__}: {e}"

    out = buf.getvalue().strip()
    if "result" in local_ns:
        suffix = repr(local_ns["result"])
        return f"{out}\n{suffix}" if out else suffix
    return out or "(no output)"


async def execute_python(code: str) -> str:
    """Run Python code inside python-sb container (OS-level isolation).

    Use print() for output, or assign to the variable ``result`` for a return value.
    For ``re.search`` / ``re.match``, verify the match is not ``None`` before ``.group()``.
    If you embed HTML returned by ``fetch_webpage``, assign it with a triple-quoted Python string
    (three double-quote characters to open and close the block) so embedded quotes and newlines
    are valid; do not paste large HTML inside one short single-line ``"..."`` literal.

    Args:
        code: Python source to execute.

    Returns:
        Captured printed output, ``result`` value, or an error string.
    """
    print(f"EXEC PYTHON (in sandbox)\n{code}")
    return await asyncio.to_thread(_execute_python_in_sandbox, code)
