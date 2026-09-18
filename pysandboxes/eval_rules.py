# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Parsing of the ``eval-*`` rules for the dynamic-code guard.

Thirteen keys: five list keys that accumulate into an allow set and a deny set,
and eight scalar keys carrying limits and modes. Rule order never changes an
outcome -- repeating a list key unions its values, and ``DENY:`` wins wherever
it appears -- so an ``include`` cannot be defeated by placement.
"""

import ast
import builtins
import difflib
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, NamedTuple

from .immutable_dict import ImmutableDict
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines
from .tools import GlobPattern

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
    allow_patterns: tuple[GlobPattern, ...]
    deny: frozenset[str]
    deny_patterns: tuple[GlobPattern, ...]

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


SYNTAX_GROUPS: dict[str, tuple[str, ...]] = {
    "arith": ("BinOp", "UnaryOp"),
    "compare": ("Compare", "BoolOp"),
    "conditional": ("If", "IfExp"),
    "loop": ("For", "While", "Break", "Continue"),
    "comprehension": ("ListComp", "SetComp", "DictComp", "GeneratorExp", "comprehension"),
    "assign": ("Assign", "AugAssign", "AnnAssign", "NamedExpr"),
    "func": ("FunctionDef", "Return", "arguments", "arg", "Lambda"),
    "async": ("AsyncFunctionDef", "Await", "AsyncFor", "AsyncWith"),
    "class": ("ClassDef",),
    "exception": ("Try", "TryStar", "Raise", "ExceptHandler"),
    "context": ("With", "withitem"),
    "import": ("Import", "ImportFrom", "alias"),
    "subscript": ("Subscript", "Slice", "Starred"),
    "fstring": ("JoinedStr", "FormattedValue"),
    # Separate from `fstring`: a t-string builds a Template whose interpolations
    # are deferred, not a string, and a configuration written before 3.14 never
    # asked for it. The nodes only exist from 3.14 on, so the group is simply
    # unused on earlier interpreters.
    "tstring": ("TemplateStr", "Interpolation"),
    "yield": ("Yield", "YieldFrom"),
}

CORE_NODES = frozenset(
    {
        "Module",
        "Expression",
        "Interactive",
        "Constant",
        "Name",
        "Load",
        "Store",
        "Del",
        "Tuple",
        "List",
        "Dict",
        "Set",
        "Expr",
        # `pass` carries no capability and is the only body a class, a try or a
        # with block can be given without opening something else. No eval-syntax
        # group names it, so leaving it out of the core would refuse
        # `class C: pass` under every possible configuration.
        "Pass",
    }
)


def _public(*types: type) -> frozenset[str]:
    """Return the public attribute names of the given types."""
    return frozenset(name for tp in types for name in dir(tp) if not name.startswith("_"))


# Computed from the stdlib rather than hardcoded, so the groups follow the
# running interpreter. str-methods drops format and format_map on purpose:
# both resolve attributes in C from the contents of the string, so no
# Attribute node exists to validate or rewrite (spec 4bis.a).
ATTRIBUTE_GROUPS: dict[str, frozenset[str]] = {
    "str-methods": _public(str) - {"format", "format_map"},
    "list-methods": _public(list),
    "dict-methods": _public(dict),
    "set-methods": _public(set),
    "tuple-methods": _public(tuple),
    "num-methods": _public(int, float),
    "bytes-methods": _public(bytes),
    "date-methods": _public(date, time, datetime, timedelta),
}

_BLIND_ATTRIBUTES = ("format", "format_map")

# Builtins that hand back, by name, a door the bounded namespace had shut.
# `getattr`, `vars`, `setattr`, `delattr`, `type`, `dir`, `globals` and
# `breakpoint` are neutralised by a guarded shim; `open`, `eval`, `exec`,
# `compile` and `__import__` reach their own guard. Either way, granting one is
# a real widening a reader should see reported.
_SENSITIVE_CALL = frozenset(
    {
        "getattr", "setattr", "delattr", "vars", "hasattr", "dir", "globals",
        "type", "breakpoint", "open", "eval", "exec", "compile", "__import__",
    }
)  # fmt: skip

LIST_KEYS: dict[str, str] = {
    "eval-syntax": "syntax",
    "eval-call": "call",
    "eval-attribute": "attribute",
    "eval-import": "imports",
    "eval-magic": "magic",
}

_GROUPS_OF_KEY: dict[str, dict[str, frozenset[str]]] = {
    "eval-syntax": {name: frozenset(nodes) for name, nodes in SYNTAX_GROUPS.items()},
    "eval-attribute": ATTRIBUTE_GROUPS,
}

_PATTERNS_FORBIDDEN = ("eval-syntax",)

EvalProfiles = ImmutableDict[str, EvalRules]
"""Profiles by name, with `""` for the default profile."""


def compile_pattern(pattern: str) -> GlobPattern:
    """Compile a list-key glob, anchored on both ends.

    `*` is the only metacharacter, exactly as in `guard_envs`. `GlobPattern`
    matches over the whole subject, so `get*` grants `getattr` and not
    `forget_me`; the previous regex needed a trailing `\\Z` to say the same,
    because `re.match()` anchors the start only.
    """
    return GlobPattern(pattern)


def _add_error(errors: list[ErrorMsg], rule: ConfigLine, detail: str) -> None:
    errors.append((f"{format_ruleref(rule)}: In {rule.rule!r}, {detail}", rule.path, rule.ln))


def _suggest(token: str, known: list[str]) -> str:
    """Return `, closest known token is 'x'` when one is close enough."""
    close = difflib.get_close_matches(token, known, n=1)
    return f", closest known token is {close[0]!r}" if close else ""


def _warn_pattern_width(key: str, pattern: str, expansion: frozenset[str]) -> None:
    """Warn when a pattern's fixed part is too short to be read at a glance."""
    fixed = pattern.replace("*", "")
    if len(fixed) >= 3:
        return
    matcher = compile_pattern(pattern)
    matched = sorted(name for name in expansion if matcher.match(name))
    logger.warning(
        "%s=%s expands to %d names on this interpreter%s — narrow the pattern or add a DENY",
        key,
        pattern,
        len(matched),
        f", including {matched[0]!r}" if matched else "",
    )


class _Accumulator:
    """Mutable per-profile accumulation, frozen into `EvalRules` at the end."""

    def __init__(self) -> None:
        self.allow: dict[str, set[str]] = {field: set() for field in LIST_KEYS.values()}
        self.allow_patterns: dict[str, list[GlobPattern]] = {field: [] for field in LIST_KEYS.values()}
        self.deny: dict[str, set[str]] = {field: set() for field in LIST_KEYS.values()}
        self.deny_patterns: dict[str, list[GlobPattern]] = {field: [] for field in LIST_KEYS.values()}
        self.scalars: dict[str, int | float | str] = {}
        self.seen_scalar: dict[str, ConfigLine] = {}

    def names(self, field: str) -> NameSet:
        return NameSet(
            allow=frozenset(self.allow[field]),
            allow_patterns=tuple(self.allow_patterns[field]),
            deny=frozenset(self.deny[field]),
            deny_patterns=tuple(self.deny_patterns[field]),
        )

    def build(self) -> EvalRules:
        syntax = self.names("syntax")
        syntax = syntax._replace(allow=syntax.allow | CORE_NODES)
        scalars = {key[len(EVAL_PREFIX) :].replace("-", "_"): value for key, value in self.scalars.items()}
        return DEFAULT_RULES._replace(
            declared=True,
            syntax=syntax,
            call=self.names("call"),
            attribute=self.names("attribute"),
            imports=self.names("imports"),
            magic=self.names("magic"),
            # Each key reaches its own field, so the value type varies per key.
            # `parse_scalar` is what guarantees the match; it is not expressible here.
            **scalars,  # type: ignore[arg-type]
        )


def _parse_list_value(
    key: str,
    field: str,
    value: str,
    rule: ConfigLine,
    acc: _Accumulator,
    errors: list[ErrorMsg],
) -> None:
    """Accumulate one list-key line into `acc`."""
    deny = value.startswith("DENY:")
    targets = value[len("DENY:") :] if deny else value
    groups = _GROUPS_OF_KEY.get(key, {})
    known = sorted(groups) + (sorted(node for node in dir(ast) if node[:1].isupper()) if key == "eval-syntax" else [])
    for raw in targets.split(","):
        token = raw.strip()
        if not token:
            _add_error(errors, rule, "empty target.")
            return
        if "*" in token:
            if key in _PATTERNS_FORBIDDEN:
                _add_error(errors, rule, f"a pattern is not accepted on {key}: the vocabulary is finite.")
                return
            _warn_pattern_width(key, token, frozenset().union(*groups.values()) if groups else frozenset())
            (acc.deny_patterns if deny else acc.allow_patterns)[field].append(compile_pattern(token))
            continue
        if token in groups:
            (acc.deny if deny else acc.allow)[field].update(groups[token])
            continue
        if key == "eval-syntax" and not hasattr(ast, token):
            _add_error(errors, rule, f"unknown syntax token {token!r}{_suggest(token, known)}.")
            return
        if key == "eval-attribute" and token in _BLIND_ATTRIBUTES and not deny:
            logger.warning(
                "eval-attribute=%s reopens an attribute the guard is structurally blind to "
                "(design spec 4bis.a): the name is resolved in C from the contents of the string, "
                "so no Attribute node exists to rewrite",
                token,
            )
        if key == "eval-call" and not deny and hasattr(builtins, token):
            if token in _SENSITIVE_CALL:
                logger.warning(
                    "eval-call=%s grants a sensitive builtin: it is neutralised by a guarded shim or "
                    "reaches its own guard, but it widens the reachable surface — grant it only if the "
                    "sub-language truly needs it",
                    token,
                )
            else:
                logger.warning("eval-call=%s adds the builtin %r to the namespace", token, token)
        (acc.deny if deny else acc.allow)[field].add(token)


def parse_rules(
    config: ConfigLines,
    errors: list[ErrorMsg],
) -> tuple[EvalProfiles, ConfigLines]:
    """Consume `eval-*` lines and return the other lines.

    Args:
        config: All remaining configuration lines.
        errors: Accumulator the caller raises on.

    Returns:
        The profiles by name -- `""` being the default one -- and the lines
        this parser did not consume.
    """
    accumulators: dict[str, _Accumulator] = {}
    others: ConfigLines = []
    for rule in config:
        if not rule.rule.startswith(EVAL_PREFIX):
            others.append(rule)
            continue
        key_part, _, value = rule.rule.partition("=")
        key, _, profile = key_part.strip().partition(":")
        value = value.strip()
        acc = accumulators.setdefault(profile, _Accumulator())
        if key in LIST_KEYS:
            _parse_list_value(key, LIST_KEYS[key], value, rule, acc, errors)
        elif key in SCALAR_KEYS:
            if key in acc.seen_scalar:
                _add_error(
                    errors,
                    rule,
                    f"{key} is set twice in this profile "
                    f"(already at line {acc.seen_scalar[key].ln}): a scalar is not a set.",
                )
                continue
            acc.seen_scalar[key] = rule
            try:
                acc.scalars[key] = parse_scalar(key, value)
            except ValueError as err:
                _add_error(errors, rule, str(err))
        else:
            _add_error(errors, rule, f"unknown key {key!r}{_suggest(key, sorted(LIST_KEYS) + list(SCALAR_KEYS))}.")
    return ImmutableDict({name: acc.build() for name, acc in accumulators.items()}), others


class LearnEvalRule(NamedTuple):
    """One construct the evaluated code needed, observed in learning mode.

    Attributes:
        key: The list key that would grant it, e.g. `eval-call`.
        name: The exact token, never a pattern.
    """

    key: str
    name: str


class LearnEvalContext(NamedTuple):
    """A call site whose own context was honoured by `eval-namespace=adaptive`.

    Attributes:
        call_site: Where the application called `eval`, e.g. `tools.py:66`.
    """

    call_site: str


_RUNTIME_OBSERVED = ("eval-attribute", "eval-magic")

_EMIT_ORDER = ("eval-syntax", "eval-import", "eval-call", "eval-attribute", "eval-magic")


def _condense_syntax(names: set[str]) -> list[str]:
    """Replace a group's nodes by the group name, only when all were seen.

    Learning must never grant more than it observed: a partially exercised
    group stays spelled out node by node.

    Args:
        names: The AST node names observed.

    Returns:
        Group names for the groups fully covered, then the leftover nodes.
    """
    remaining = set(names)
    tokens: list[str] = []
    for group, nodes in SYNTAX_GROUPS.items():
        if set(nodes) <= remaining:
            tokens.append(group)
            remaining -= set(nodes)
    return sorted(tokens) + sorted(remaining)


def generate_rules(learn: set[Any]) -> list[str]:
    """Emit the `eval-*` lines for what the evaluated code actually needed.

    Never a pattern: generalising from a sample is precisely what learning
    must not do.

    Args:
        learn: The learning set, holding `LearnEvalRule` and
            `LearnEvalContext` entries among the other guards'.

    Returns:
        The lines for the `<learning_guard_eval>` block, empty when nothing
        was observed.
    """
    observed: dict[str, set[str]] = {}
    sites: set[str] = set()
    for entry in learn:
        if isinstance(entry, LearnEvalRule):
            observed.setdefault(entry.key, set()).add(entry.name)
        elif isinstance(entry, LearnEvalContext):
            sites.add(entry.call_site)
    if not observed and not sites:
        return []
    lines: list[str] = []
    for key in _EMIT_ORDER:
        names = observed.get(key)
        if key == "eval-call" and sites:
            # The namespace came from the call site, so eval-call was never
            # consulted: emitting it would produce rules that are at once
            # unused and misleading -- a reader would take them for the
            # reachable surface.
            lines.append("# eval-call not emitted: the namespace came from the call site")
            lines.append(f"#   ({', '.join(sorted(sites))}). Set eval-namespace=closed to declare it here.")
            continue
        if not names:
            continue
        tokens = _condense_syntax(names) if key == "eval-syntax" else sorted(names)
        suffix = "                    # ⚠ runtime-observed" if key in _RUNTIME_OBSERVED else ""
        lines.append(f"{key}={', '.join(tokens)}{suffix}")
    return lines
