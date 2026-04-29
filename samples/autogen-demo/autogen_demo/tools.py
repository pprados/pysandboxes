"""Tools exposed to the assistant via AutoGen (model issues tool calls)."""

import asyncio
import io
import json
import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# region agent log
_DEBUG_LOG_PATH = "/home/philippe-prados/workspace/pysandboxes/.cursor/debug-12736d.log"


def _agent_dbg(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
    *,
    run_id: str | None = None,
) -> None:
    rid = run_id if run_id is not None else os.environ.get("AGENT_DEBUG_RUN_ID", "pre-fix")
    payload = {
        "sessionId": "12736d",
        "runId": rid,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# endregion

_DEFAULT_TIMEOUT = 15.0
_MAX_BODY_CHARS = 8000

_ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"re", "math", "json", "itertools", "functools", "collections", "operator", "string"}
)


def _safe_import(
    name: str,
    globals_: dict[str, Any] | None = None,
    locals_: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if level != 0 or not name or name.split(".")[0] not in _ALLOWED_IMPORTS:
        raise ImportError(
            f"import of {name!r} is not allowed. "
            f"Allowed: {', '.join(sorted(_ALLOWED_IMPORTS))}. "
            "For regex, `re` is also available without importing."
        )
    return __import__(name, globals_, locals_, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    return {
        "__import__": _safe_import,
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
        "re": re,
    }


def _execute_python_sync(code: str) -> str:
    """Run Python in a restricted namespace (demo only — not an OS sandbox)."""
    # region agent log
    _agent_dbg(
        "H1-H3",
        "tools.py:_execute_python_sync:entry",
        "code_shape",
        {
            "code_len": len(code),
            "line_count": code.count("\n") + 1 if code else 0,
            "n_dquote": code.count('"'),
            "n_squote": code.count("'"),
            "preview_head": (code[:120].replace("\n", "\\n") if code else ""),
        },
    )
    # endregion
    buf = io.StringIO()

    def safe_print(*args: object, **kwargs: Any) -> None:
        print(*args, file=buf, **kwargs)

    builtins_dict = _safe_builtins()
    builtins_dict["print"] = safe_print
    g: dict[str, Any] = {"__builtins__": builtins_dict}
    local_ns: dict[str, Any] = {}
    try:
        compiled = compile(code, "<execute_python>", "exec")
    except SyntaxError as e:
        logger.warning("execute_python failed: %s: %s", type(e).__name__, e)
        # region agent log
        _agent_dbg(
            "H1-H3-H5",
            "tools.py:_execute_python_sync:syntax_error",
            "compile_failed",
            {
                "exc_type": type(e).__name__,
                "lineno": getattr(e, "lineno", None),
                "offset": getattr(e, "offset", None),
                "text": (e.text.strip() if e.text else None),
            },
        )
        # endregion
        base = f"Error: {type(e).__name__}: {e}"
        if "unterminated string" in str(e).lower() or "invalid syntax" in str(e).lower():
            return (
                base + " Hint: for HTML from fetch_webpage, assign it with triple-quoted strings "
                '(html = """...""" or \'\'\'...\'\'\'), not a single "..." line with raw HTML inside.'
            )
        return base
    except Exception as e:
        logger.warning("execute_python failed: %s: %s", type(e).__name__, e)
        return f"Error: {type(e).__name__}: {e}"
    try:
        exec(compiled, g, local_ns)
    except Exception as e:
        logger.warning("execute_python failed: %s: %s", type(e).__name__, e)
        return f"Error: {type(e).__name__}: {e}"
    out = buf.getvalue().strip()
    if "result" in local_ns:
        suffix = repr(local_ns["result"])
        return f"{out}\n{suffix}" if out else suffix
    return out or "(no output)"


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


async def execute_python(code: str) -> str:
    """Run Python code in a restricted namespace (demo only — not an OS sandbox).

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
    return await asyncio.to_thread(_execute_python_sync, code)
