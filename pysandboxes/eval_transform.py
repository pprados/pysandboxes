# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The two-phase transform applied to dynamically evaluated source.

Phase 1 reads the input AST and writes nothing. Phase 2 produces the output
AST. The phases are watertight and injected nodes never pass back through the
validator -- without that invariant, the helper calls phase 2 injects would
themselves violate the user's `eval-call` and `eval-magic` rules.

Phase 1 is a fail-fast, not a barrier: it inspects names as they are written,
and Python offers several ways to reach a function without writing its name
where the validator looks. The barriers are the bounded namespace and
`eval_runtime`.
"""

import ast
import copy
import logging
from importlib import resources
from typing import NamedTuple

from .e import EvalSyntaxRejected
from .eval_rules import SYNTAX_GROUPS, EvalRules

logger = logging.getLogger(__name__)

RESERVED_PREFIX = "__sb_"

# Structurally always available, each gated by its own check rather than by
# eval-syntax: Attribute by eval-attribute/eval-magic and __sb_getattr__,
# Call by eval-call, keyword by the Call it belongs to.
_ALWAYS_AVAILABLE = frozenset({"Attribute", "Call", "keyword"})

# Operator and context markers carry no capability of their own: the spec's
# `arith` group names BinOp, not Add.
_MARKERS: tuple[type, ...] = (ast.operator, ast.cmpop, ast.boolop, ast.unaryop, ast.expr_context)

_GROUP_OF_NODE: dict[str, str] = {node: group for group, nodes in SYNTAX_GROUPS.items() for node in nodes}

_WARNED_REMEDY: dict[str, str] = {
    "eval-magic": "opens the whole type hierarchy",
    "eval-import": "a module exposes everything it imports in turn",
}

# Modules an evaluated fragment has no legitimate reason to reach, on top of
# whatever `guard_import` already flags. The threshold is not the same on both
# sides and must not be aligned: a whole application imports `os` as a matter
# of course, while a sub-language computing over supplied data never needs it.
# So `eval-import` warns about strictly more than `python-import`, never less.
_EVAL_WARNED_MODULES = frozenset({"os", "sys", "socket", "builtins", "shutil"})

# Read rather than restated, so the shared half cannot drift: a module printed
# under `# ⚠ Dangerous!` by one guard and passed over in silence by the other
# reads as an oversight. Loaded at import time, before arming, so the read is
# never charged to the user's own `python-import` rules.
_WARNED_MODULES = (
    frozenset(resources.files(__package__ or "pysandboxes").joinpath("modules_blacklist.txt").read_text().split())
    | _EVAL_WARNED_MODULES
)


class Violation(NamedTuple):
    """One refused construct, with the line that would allow it.

    Attributes:
        lineno: 1-based line in the evaluated source.
        col: 0-based column.
        message: What was refused, in the user's own vocabulary.
        remedy: The exact configuration line to paste.
        warning: Non-empty when granting the remedy is a real widening.
    """

    lineno: int
    col: int
    message: str
    remedy: str
    warning: str = ""


def _depth(node: ast.AST) -> int:
    """Return the static nesting depth of `node`, counting itself as one.

    Iterative: the tree is measured before any recursive visit, so a source nested deeper than the interpreter's
    recursion limit is refused instead of raising `RecursionError`.
    """
    deepest = 0
    pending = [(node, 1)]
    while pending:
        current, depth = pending.pop()
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(current))
    return deepest


# Fields holding an identifier the code binds or names: def and class names, arguments, keywords, import aliases,
# except, global and nonlocal names, match captures, type parameters. Name and Attribute are checked by their own
# visitors.
_IDENTIFIER_FIELDS = ("name", "asname", "arg", "names", "rest", "kwd_attrs")


class _Validator(ast.NodeVisitor):
    """Collect every violation instead of raising on the first.

    One pass, one report, one correction round for whoever wrote the code --
    human or model.
    """

    def __init__(self, rules: EvalRules) -> None:
        self.rules = rules
        self.violations: list[Violation] = []

    def _add(self, node: ast.AST, message: str, remedy: str, warning: str = "") -> None:
        self.violations.append(
            Violation(
                lineno=getattr(node, "lineno", 0),
                col=getattr(node, "col_offset", 0),
                message=message,
                remedy=remedy,
                warning=warning,
            )
        )

    def _check_identifier(self, node: ast.AST, name: str, kind: str) -> None:
        if name.startswith(RESERVED_PREFIX):
            self._add(
                node,
                f"{kind} {name!r} uses the reserved prefix {RESERVED_PREFIX!r}",
                "rename it: the prefix belongs to the guard's own helpers",
            )
            return
        if name.startswith("__") and name.endswith("__") and not self.rules.magic.allows(name):
            self._add(
                node,
                f"{kind} {name!r} is not allowed",
                f"eval-magic={name}",
                _WARNED_REMEDY["eval-magic"],
            )

    def generic_visit(self, node: ast.AST) -> None:
        name = type(node).__name__
        for field in _IDENTIFIER_FIELDS:
            value = getattr(node, field, None)
            for identifier in value if isinstance(value, list) else [value]:
                if isinstance(identifier, str) and identifier.startswith(RESERVED_PREFIX):
                    self._add(
                        node,
                        f"{name} name {identifier!r} uses the reserved prefix {RESERVED_PREFIX!r}",
                        "rename it: the prefix belongs to the guard's own helpers",
                    )
        if not isinstance(node, _MARKERS) and name not in _ALWAYS_AVAILABLE and not self.rules.syntax.allows(name):
            group = _GROUP_OF_NODE.get(name)
            remedy = f"eval-syntax={group}" if group else f"eval-syntax={name}"
            if group:
                remedy += f"        (or, narrower: eval-syntax={name})"
            self._add(node, f"{name!r} is not allowed", remedy)
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._check_identifier(node, node.id, "identifier")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.ctx, ast.Load):
            self._add(
                node,
                f"attribute {node.attr!r} in {type(node.ctx).__name__} context is not allowed",
                "a sub-language computing over supplied data does not mutate attributes",
            )
        self._check_identifier(node, node.attr, "attribute")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and not self.rules.call.allows(node.func.id):
            if not node.func.id.startswith(RESERVED_PREFIX):
                self._add(node, f"call to {node.func.id!r} is not allowed", f"eval-call={node.func.id}")
        self.generic_visit(node)

    def _check_module(self, node: ast.AST, module: str) -> None:
        if not self.rules.imports.allows(module):
            root = module.partition(".")[0]
            self._add(
                node,
                f"import {module!r} is not allowed",
                f"eval-import={module}",
                f"{root} opens a route to the host process or its frames" if root in _WARNED_MODULES else "",
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._check_module(node, node.module or "")
        self.generic_visit(node)


def validate(tree: ast.AST, rules: EvalRules) -> list[Violation]:
    """Return every way `tree` leaves the sub-language `rules` describes.

    Args:
        tree: The parsed input AST, before any injection.
        rules: The resolved profile.

    Returns:
        The violations in source order, empty when the tree is accepted.
    """
    depth = _depth(tree)
    if depth > rules.max_depth:
        # The visit below recurses as deep as the tree: it is not run on a tree already refused for its depth.
        return [Violation(1, 0, f"the source nests {depth} levels deep", f"eval-max-depth={depth}")]
    validator = _Validator(rules)
    try:
        validator.visit(tree)
    except RecursionError:
        # An eval-max-depth set past what the interpreter's stack can walk: the tree is refused all the same.
        return [Violation(1, 0, f"the source nests {depth} levels deep", f"eval-max-depth={depth}")]
    count = sum(1 for _ in ast.walk(tree))
    if count > rules.max_nodes:
        validator.violations.append(Violation(1, 0, f"the source holds {count} nodes", f"eval-max-nodes={count}"))
    return sorted(validator.violations, key=lambda v: (v.lineno, v.col))


def render_violation(source: str, violation: Violation) -> str:
    """Render one violation as its own block, caret line included."""
    lines = source.splitlines()
    text = lines[violation.lineno - 1].strip() if 0 < violation.lineno <= len(lines) else ""
    block = [f"  line {violation.lineno}, col {violation.col}: {violation.message}"]
    if text:
        block.append(f"      {text}")
        block.append(f"      {'^' * len(text)}")
    remedy = f"    add: {violation.remedy}"
    if violation.warning:
        remedy += f"    ⚠ {violation.warning}"
    block.append(remedy)
    return "\n".join(block)


def render_report(source_ref: str, source: str, violations: list[Violation]) -> str:
    """Render the spec's one-report-every-violation block."""
    header = f"{len(violations)} rules violated in {source_ref}"
    return "\n\n".join([header] + [render_violation(source, v) for v in violations])


def raise_if_rejected(source_ref: str, source: str, violations: list[Violation]) -> None:
    """Raise `EvalSyntaxRejected` when there is anything to report.

    `violations` on the exception holds **one rendered block per violation**,
    built from the violation list itself and never by re-splitting the
    rendered report -- a reader of `err.violations` expects to iterate the
    refusals, not to receive the whole text as a single element.

    Args:
        source_ref: How the source is named in tracebacks, e.g. `<eval:llm>`.
        source: The evaluated source, for the caret lines.
        violations: What `validate` returned.

    Raises:
        EvalSyntaxRejected: At least one violation.
    """
    if not violations:
        return
    lines = source.splitlines()
    first = violations[0]
    raise EvalSyntaxRejected(
        f"{len(violations)} rules violated in {source_ref}",
        [render_violation(source, violation) for violation in violations],
        lineno=first.lineno,
        offset=first.col,
        text=lines[first.lineno - 1] if 0 < first.lineno <= len(lines) else "",
    )


_GUARDED_BINOPS: dict[type, str] = {ast.Pow: "**", ast.Mult: "*", ast.Add: "+", ast.LShift: "<<", ast.Mod: "%"}


def _call(name: str, args: list[ast.expr]) -> ast.Call:
    """Build a call on one of the `__sb_` helpers."""
    return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=args, keywords=[])


def _load(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Load())


def _store(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Store())


def _tick() -> ast.Expr:
    return ast.Expr(value=_call("__sb_tick__", []))


class _Injector(ast.NodeTransformer):
    """Rewrite the accepted tree into one that enforces at runtime.

    Attribute reads are rewritten: `Attribute` in `Store` or `Del` context was
    already refused by phase 1. A subscript store or delete goes through
    `__sb_writable__`, which refuses to write into an object the application
    supplied.
    """

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.ctx, ast.Load):
            node.value = _call("__sb_writable__", [node.value])
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.ctx, ast.Load):
            return node
        return ast.copy_location(
            _call("__sb_getattr__", [node.value, ast.Constant(value=node.attr)]),
            node,
        )

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        symbol = _GUARDED_BINOPS.get(type(node.op))
        if symbol is None:
            return node
        return ast.copy_location(
            _call("__sb_binop__", [ast.Constant(value=symbol), node.left, node.right]),
            node,
        )

    def visit_FormattedValue(self, node: ast.FormattedValue) -> ast.AST:
        self.generic_visit(node)
        if node.format_spec is None:
            return node
        # The spec is evaluated once, then checked and applied by the helper; the field keeps no spec of its own.
        value = _call("__sb_format__", [node.value, ast.Constant(value=node.conversion), node.format_spec])
        return ast.copy_location(ast.FormattedValue(value=value, conversion=-1, format_spec=None), node)

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST | list[ast.stmt]:
        self.generic_visit(node)
        symbol = _GUARDED_BINOPS.get(type(node.op))
        if symbol is None or not isinstance(node.target, ast.Name | ast.Subscript):
            return node
        setup: list[ast.stmt] = []
        if isinstance(node.target, ast.Subscript):
            # The container and the key are evaluated once, as the augmented assignment does. A key holding a
            # slice is no value to keep aside: its bounds are evaluated twice.
            setup.append(ast.Assign(targets=[_store("__sb_container__")], value=node.target.value))
            key = node.target.slice
            if not any(isinstance(part, ast.Slice) for part in ast.walk(key)):
                setup.append(ast.Assign(targets=[_store("__sb_key__")], value=key))
                key = _load("__sb_key__")
            read: ast.expr = ast.Subscript(value=_load("__sb_container__"), slice=key, ctx=ast.Load())
            target: ast.expr = ast.Subscript(value=_load("__sb_container__"), slice=copy.deepcopy(key), ctx=ast.Store())
        else:
            read = _load(node.target.id)
            target = node.target
        assign = ast.Assign(
            targets=[target], value=_call("__sb_binop__", [ast.Constant(value=symbol + "="), read, node.value])
        )
        return [ast.copy_location(statement, node) for statement in setup + [assign]]

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        node.body = [_tick()] + node.body
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AST:
        self.generic_visit(node)
        node.body = [_tick()] + node.body
        return node

    def visit_While(self, node: ast.While) -> ast.AST:
        self.generic_visit(node)
        node.body = [_tick()] + node.body
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.AST:
        self.generic_visit(node)
        node.iter = ast.copy_location(_call("__sb_iter__", [node.iter]), node.iter)
        return node

    def _bracket(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        node.body = [
            ast.Expr(value=_call("__sb_enter__", [])),
            ast.Try(
                body=node.body,
                handlers=[],
                orelse=[],
                finalbody=[ast.Expr(value=_call("__sb_leave__", []))],
            ),
        ]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._bracket(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._bracket(node)

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        # A lambda body is one expression, so the enter/leave brackets a
        # FunctionDef gets inline cannot be injected here: the lambda object is
        # wrapped instead, so its calls charge a frame like any other function.
        self.generic_visit(node)
        return ast.copy_location(_call("__sb_func__", [node]), node)


def inject(tree: ast.AST) -> ast.AST:
    """Rewrite an accepted tree so the remaining risks are enforced at runtime.

    Line and column numbers keep pointing at the user's source, so a traceback
    from inside the evaluated code stays readable.

    Args:
        tree: The tree phase 1 accepted. Rewritten in place.

    Returns:
        The same tree, with helper calls injected and locations fixed.
    """
    transformed = _Injector().visit(tree)
    ast.fix_missing_locations(transformed)
    return transformed


def learn_targets(violations: list[Violation]) -> list[tuple[str, str]]:
    """Turn refusals into `(key, name)` pairs learning can emit.

    `Violation.remedy` is by contract either `<key>=<value>`, optionally
    followed by two spaces and a parenthetical, or a prose sentence with no
    `=` at all -- the reserved-prefix and attribute-store refusals, which no
    rule can grant. Only the five list keys are kept, so an
    `eval-max-nodes=...` remedy is never mistaken for a rule.

    Args:
        violations: What `validate` returned.

    Returns:
        One `(key, name)` pair per refusal a list key could grant.
    """
    from .eval_rules import LIST_KEYS

    targets: list[tuple[str, str]] = []
    for violation in violations:
        head = violation.remedy.split("  ", maxsplit=1)[0].strip()
        key, sep, name = head.partition("=")
        if sep and key in LIST_KEYS and name:
            targets.append((key, name))
    return targets
