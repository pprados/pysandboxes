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
import logging
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

_WARNED_MODULES = frozenset({"os", "sys", "subprocess", "importlib", "ctypes", "socket", "builtins", "shutil"})


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
    """Return the static nesting depth of `node`, counting itself as one."""
    children = list(ast.iter_child_nodes(node))
    if not children:
        return 1
    return 1 + max(_depth(child) for child in children)


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
                f"{root} exposes the process environment" if root in _WARNED_MODULES else "",
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
    validator = _Validator(rules)
    validator.visit(tree)
    count = sum(1 for _ in ast.walk(tree))
    if count > rules.max_nodes:
        validator.violations.append(Violation(1, 0, f"the source holds {count} nodes", f"eval-max-nodes={count}"))
    depth = _depth(tree)
    if depth > rules.max_depth:
        validator.violations.append(Violation(1, 0, f"the source nests {depth} levels deep", f"eval-max-depth={depth}"))
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


_GUARDED_BINOPS: dict[type, str] = {ast.Pow: "**", ast.Mult: "*", ast.Add: "+"}


def _call(name: str, args: list[ast.expr]) -> ast.Call:
    """Build a call on one of the `__sb_` helpers."""
    return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=args, keywords=[])


def _tick() -> ast.Expr:
    return ast.Expr(value=_call("__sb_tick__", []))


class _Injector(ast.NodeTransformer):
    """Rewrite the accepted tree into one that enforces at runtime.

    Only reads are rewritten: `Attribute` in `Store` or `Del` context was
    already refused by phase 1, so a fourth helper would have nothing to do.
    """

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
