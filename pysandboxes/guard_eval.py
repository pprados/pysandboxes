# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard for code that arrives as a string at runtime.

`builtins.eval`, `builtins.exec` and `builtins.compile` are patched here. A
guarded call parses the source, validates it against the sub-language the
`eval-*` rules describe, rewrites it so the remaining risks are enforced by
`eval_runtime`, and runs it in a dedicated thread under a budget and a
timeout the caller can recover from.

Two deviations from the design spec are recorded here so a later reader does
not "restore" them:

- `SENSITIVE_API["dynamic-code"]` holds three names, not the six of spec 11.
  `builtins.__import__` belongs to `guard_import`, which has its own rules;
  `code.compile_command` and `code.InteractiveInterpreter.runsource` reach the
  three builtins anyway and patching them would double-count one call.
- Spec 8.1 states that CPython's automatic 159-builtin injection is never
  honoured in any mode, and its own table then gives `eval-namespace=caller`
  as honouring it. The bold sentence governs `adaptive` and `closed`; `caller`
  is the debugging escape hatch and does honour injection, warned at load.
"""

import builtins
import logging
import types
from typing import Any

from .eval_rules import EvalRules
from .eval_runtime import HELPERS

logger = logging.getLogger(__name__)

CAPABILITY_BUILTINS = frozenset(
    {
        "getattr",
        "setattr",
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "type",
        "vars",
        "globals",
        "dir",
        "breakpoint",
    }
)
"""Builtins that reopen by name a door the bounded namespace had shut."""

STRONG_MODULES = frozenset({"os", "subprocess", "importlib", "ctypes", "socket", "posix", "nt", "_socket"})
"""Modules whose callables hand over the host.

Implementation modules are named alongside the facades a reader would write,
because `__module__` reports where a callable was defined, not where it is
reached. Measured on this interpreter: `os.listdir` and `os.system` report
`posix`, so `os` alone would grade them weak. `subprocess`, `importlib`,
`ctypes` and `socket` all report their facade and need no such twin. `nt` is
the Windows counterpart of `posix`, untested here. `_socket` is listed
because `_socket.socket` is a distinct object from `socket.socket` and
reports `_socket`; the facade class itself reports `socket`.
"""

# Matched on the name alone, deliberately, after two narrower tests failed:
#
# - `__module__` cannot qualify it. `open.__module__` is `_io`, not
#   `builtins`, so requiring the latter dropped the most dangerous entry of
#   the whole list.
# - Identity cannot either. The other guards patch `builtins.open` when they
#   arm, so any object captured here at import time stops being the one a
#   caller can pass once the sandbox is active. A guard must not key its
#   classification on the identity of objects another guard replaces.
#
# The cost is an application function of its own called `open` or `type`
# graded strong rather than weak. That is a message wording, not a hole: weak
# findings are reported too, so the name test over-warns where the narrower
# ones went silent.

_SCALARS = (int, float, complex, str, bytes, bool, type(None))
_CONTAINERS = (list, tuple, set, frozenset, dict)

_warned: set[tuple[str, str]] = set()


def _reset_context_warnings() -> None:
    """Clear the deduplication set. Test hook only."""
    _warned.clear()


def classify_context_value(value: Any) -> str:
    """Grade one name a caller put in an eval context.

    Returns:
        `"strong"` when the value grants what the guard closes elsewhere,
        `"weak"` when it runs code the application chose, `""` for data.
    """
    if isinstance(value, types.ModuleType):
        return "strong"
    if callable(value):
        if getattr(value, "__name__", "") in CAPABILITY_BUILTINS:
            return "strong"
        module = getattr(value, "__module__", "") or ""
        if module.partition(".")[0] in STRONG_MODULES:
            return "strong"
        return "weak"
    if isinstance(value, _SCALARS):
        return ""
    if isinstance(value, _CONTAINERS):
        items = value.values() if isinstance(value, dict) else value
        return "" if all(isinstance(item, _SCALARS) for item in items) else "weak"
    return "weak"


_GRADE_HELP = {
    "strong": "the evaluated code can reach everything it exposes",
    "weak": "it runs code outside the sub-language",
}


def warn_about_context(context: dict[str, Any], source_ref: str) -> None:
    """Log one finding per graded name, once per call site.

    `logger.warning`, not `warnings.warn`: every other guard in the package
    reports on the module logger, and a lone `warnings` channel here would be
    the one finding a host's existing logging configuration never saw.

    The deduplication set is kept here because a logger offers no equivalent of
    the `warnings` "once" filter, and the call site is named *in the message*
    because a log record is attributed to the frame that emitted it -- there is
    no `stacklevel` to point it at the application's own `eval()` line.

    Args:
        context: The caller-supplied globals.
        source_ref: Where the call sits, e.g. `tools.py:66`.
    """
    for name, value in context.items():
        if name == "__builtins__":
            continue
        grade = classify_context_value(value)
        if not grade:
            continue
        key = (source_ref, name)
        if key in _warned:
            continue
        _warned.add(key)
        kind = "module" if isinstance(value, types.ModuleType) else "value"
        logger.warning(
            "eval() context provides %s %r at %s\n    %s\n    acknowledge with: eval-call=%s"
            "        (or use eval-namespace=closed)",
            kind,
            name,
            source_ref,
            _GRADE_HELP[grade],
            name,
        )


def _builtins_from(rules: EvalRules) -> dict[str, Any]:
    """Build `__builtins__` from `eval-call`, and from nothing else.

    An empty result is legal and coherent: CPython does not repopulate a
    `__builtins__` key that is present but empty, so a call-free profile
    evaluates arithmetic and comparison over the data the wrapper passed in --
    exactly the calculator the samples ship.

    `builtins` is reached through the module-level import rather than a local
    one: a deferred import runs after arming and is charged to the user's own
    `python-import` rules, which a guard building its namespace must not be.
    """
    allowed = {}
    for name in dir(builtins):
        if rules.call.allows(name):
            allowed[name] = getattr(builtins, name)
    for name in rules.call.allow:
        if name not in allowed and hasattr(builtins, name):
            allowed[name] = getattr(builtins, name)
    return allowed


def build_namespace(
    rules: EvalRules,
    *,
    caller_globals: dict[str, Any] | None,
    names: dict[str, Any] | None,
    from_wrapper: bool,
) -> dict[str, Any]:
    """Return the globals the evaluated code will see.

    Implements the five rows of spec 8.1. The dividing line for the patched
    builtin is `caller_globals is None`, not "arguments were passed":
    `eval(e, None, {"x": 1})` still runs against the caller's module globals,
    so only the first parameter decides.

    `eval-namespace=caller` never reaches here. It is a wrapper-level
    decision: the call goes straight to the raw builtin, because a namespace
    that honours CPython's injection must also skip the rewrite -- injected
    `__sb_getattr__` calls into a namespace that does not carry the helpers
    would raise `NameError` on the first attribute read.

    Args:
        rules: The resolved profile.
        caller_globals: What the application passed as `eval`'s second
            argument, or None.
        names: Wrapper-supplied data, merged in. `guarded_eval` only.
        from_wrapper: The call came through `guarded_eval`, which is itself a
            statement of intent and never takes the adaptive branch.

    Returns:
        The globals mapping. Under the honoured-context rows this is the
        caller's own dict, mutated in place with a `__builtins__` key when it
        had none.
    """
    if not from_wrapper and caller_globals is not None:
        if rules.namespace == "adaptive":
            if "__builtins__" not in caller_globals:
                caller_globals["__builtins__"] = _builtins_from(rules)
            caller_globals.update(HELPERS)
            return caller_globals
    namespace: dict[str, Any] = {"__builtins__": _builtins_from(rules)}
    namespace.update(HELPERS)
    if names:
        namespace.update(names)
    return namespace
