# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Parsing of the ``eval-*`` rules for the dynamic-code guard.

Thirteen keys: five list keys that accumulate into an allow set and a deny set,
and eight scalar keys carrying limits and modes. Rule order never changes an
outcome -- repeating a list key unions its values, and ``DENY:`` wins wherever
it appears -- so an ``include`` cannot be defeated by placement.
"""

import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)

EVAL_PREFIX = "eval-"

_SIZE_SUFFIX: dict[str, int] = {"KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}
_TIME_SUFFIX: dict[str, float] = {"ms": 0.001, "s": 1.0, "m": 60.0}

NAMESPACE_MODES = ("adaptive", "closed", "caller")

_SIZE_KEYS = ("eval-max-alloc",)
_TIME_KEYS = ("eval-timeout",)
_INT_KEYS = (
    "eval-max-iterations",
    "eval-max-call-depth",
    "eval-max-depth",
    "eval-max-nodes",
    "eval-max-leaked-threads",
)
SCALAR_KEYS = _SIZE_KEYS + _TIME_KEYS + _INT_KEYS + ("eval-namespace",)


class NameSet(NamedTuple):
    """One list key, as two unordered sets plus their compiled patterns.

    Attributes:
        allow: Exact names granted.
        allow_patterns: Compiled globs granting every name they match.
        deny: Exact names refused, whatever the allow side says.
        deny_patterns: Compiled globs refusing every name they match.
    """

    allow: frozenset[str]
    allow_patterns: tuple[re.Pattern[str], ...]
    deny: frozenset[str]
    deny_patterns: tuple[re.Pattern[str], ...]

    def allows(self, name: str) -> bool:
        """Return whether `name` is granted.

        ``DENY`` wins, always: a reader resolves any name by asking one
        question and never by looking at where a line sits in the file.
        """
        if name in self.deny or any(p.match(name) for p in self.deny_patterns):
            return False
        return name in self.allow or any(p.match(name) for p in self.allow_patterns)


EMPTY_NAMES = NameSet(allow=frozenset(), allow_patterns=(), deny=frozenset(), deny_patterns=())


class EvalRules(NamedTuple):
    """The accepted sub-language and its budgets, for one profile.

    Attributes:
        declared: Whether the profile carries at least one `eval-*` key. False
            means `eval`, `exec` and `compile` are refused outright.
        syntax: Allowed `ast` node class names, groups already expanded.
        call: Names callable from the evaluated source, which is also what the
            namespace's `__builtins__` is built from.
        attribute: Ordinary attribute names `__sb_getattr__` lets through.
        imports: Module names `import` may name.
        magic: Dunder names allowed as attributes or identifiers.
        namespace: One of `adaptive`, `closed`, `caller`.
        max_iterations: Loop and comprehension iterations before interruption.
        max_call_depth: Runtime call depth of evaluated functions.
        max_depth: Static AST nesting accepted by phase 1.
        max_nodes: Static node count accepted by phase 1.
        max_alloc: Bound, in bytes, on the allocations `__sb_binop__` sees.
        timeout: Wall-clock seconds before the watchdog interrupts.
        max_leaked_threads: Uncooperative threads tolerated before new calls
            are refused.
    """

    declared: bool
    syntax: NameSet
    call: NameSet
    attribute: NameSet
    imports: NameSet
    magic: NameSet
    namespace: str
    max_iterations: int
    max_call_depth: int
    max_depth: int
    max_nodes: int
    max_alloc: int
    timeout: float
    max_leaked_threads: int


DEFAULT_RULES = EvalRules(
    declared=False,
    syntax=EMPTY_NAMES,
    call=EMPTY_NAMES,
    attribute=EMPTY_NAMES,
    imports=EMPTY_NAMES,
    magic=EMPTY_NAMES,
    namespace="adaptive",
    max_iterations=1_000_000,
    max_call_depth=20,
    max_depth=20,
    max_nodes=5_000,
    max_alloc=10_000_000,
    timeout=5.0,
    max_leaked_threads=4,
)


def parse_scalar(key: str, value: str) -> int | float | str:
    """Parse one scalar key's value.

    `_` is a digit separator. Sizes take a decimal `KB`/`MB`/`GB` suffix,
    durations a `ms`/`s`/`m` one. `DENY:` and patterns are list-key only and
    are reported as configuration errors rather than given some invented
    meaning.

    Args:
        key: The `eval-*` key being parsed.
        value: Its right-hand side, already stripped.

    Returns:
        An `int` for counts and sizes, a `float` of seconds for durations, the
        mode string for `eval-namespace`.

    Raises:
        ValueError: The value is malformed for this key.
    """
    if value.startswith("DENY:") or "*" in value:
        raise ValueError(f"{key}: `DENY:` and patterns apply to list keys only.")
    if key == "eval-namespace":
        if value not in NAMESPACE_MODES:
            raise ValueError(f"{key}: unknown mode {value!r}, expected one of {list(NAMESPACE_MODES)}.")
        return value
    raw = value.replace("_", "")
    if key in _TIME_KEYS:
        for suffix in ("ms", "s", "m"):
            if raw.endswith(suffix):
                return float(raw[: -len(suffix)]) * _TIME_SUFFIX[suffix]
        return float(raw)
    if key in _SIZE_KEYS:
        for suffix, factor in _SIZE_SUFFIX.items():
            if raw.upper().endswith(suffix):
                return int(float(raw[: -len(suffix)]) * factor)
        return int(raw)
    return int(raw)
