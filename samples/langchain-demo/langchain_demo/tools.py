"""Tools exposed to the chat model via LangChain's tool API."""

import io
import logging
import re
from typing import Annotated, Any

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0
_MAX_BODY_CHARS = 8000

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


@tool
def fetch_webpage(url: str) -> str:
    """HTTP GET a URL and return response body as text (truncated for large pages).

    Args:
        url: Absolute http(s) URL to fetch.

    Returns:
        Response body text, or an error string.
    """
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            text = response.text
    except Exception as e:
        logger.warning("fetch_webpage failed for %s: %s", url, e, exc_info=True)
        return f"Error fetching URL: {type(e).__name__}: {e}"
    if len(text) > _MAX_BODY_CHARS:
        return text[:_MAX_BODY_CHARS] + "\n... [truncated]"
    return text



#%% ---------------------
@tool
def calculator(
    expression: Annotated[str, "Mathematical expression to evaluate"]
) -> str:
    """
    Evaluate a mathematical expression and return the result.

    Args:
        expression: A valid Python mathematical expression (e.g., "2+2",
                   "sqrt(16)", "10**2")

    Returns:
        The result of the evaluation as a string

    Examples:
        >>> calculator("2 + 2")
        '4'
        >>> calculator("10 * 5")
        '50'
    """
    try:
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
        }

        import math
        allowed_names.update({
            name: getattr(math, name)
            for name in dir(math)
            if not name.startswith("_")
        })

        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {str(e)}"


#%% ---------------------
# Stdlib modules execute_python may load via `import` (restricted __import__).
_ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"re", "math", "json", "itertools", "functools", "collections", "operator", "string"}
)



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


@tool
def execute_python(code: str) -> str:
    """Run Python code in a restricted namespace (demo only — not an OS sandbox).

    Use print() for output, or assign to the variable ``result`` for a return value.
    For ``re.search`` / ``re.match``, verify the match is not ``None`` before ``.group()``.

    Args:
        code: Python source to execute.

    Returns:
        Captured printed output, ``result`` value, or an error string.
    """
    buf = io.StringIO()

    def safe_print(*args: object, **kwargs: Any) -> None:
        print(*args, file=buf, **kwargs)

    builtins_dict = _safe_builtins()
    builtins_dict["print"] = safe_print
    g: dict[str, Any] = {"__builtins__": builtins_dict}
    local_ns: dict[str, Any] = {}
    try:
        exec(compile(code, "<execute_python>", "exec"), g, local_ns)
    except Exception as e:
        logger.warning("execute_python failed: %s: %s", type(e).__name__, e)
        return f"Error: {type(e).__name__}: {e}"
    out = buf.getvalue().strip()
    if "result" in local_ns:
        suffix = repr(local_ns["result"])
        return f"{out}\n{suffix}" if out else suffix
    return out or "(no output)"
