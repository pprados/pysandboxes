# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Phase 1 validation and phase 2 injection."""

import ast

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalSyntaxRejected
from pysandboxes.eval_rules import DEFAULT_RULES, SYNTAX_GROUPS, NameSet
from pysandboxes.eval_transform import (
    RESERVED_PREFIX,
    Violation,
    raise_if_rejected,
    render_report,
    validate,
)


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _syntax(*groups: str) -> NameSet:
    from pysandboxes.eval_rules import CORE_NODES

    nodes = set(CORE_NODES)
    for group in groups:
        nodes.update(SYNTAX_GROUPS[group])
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _check(source: str, **kwargs: object) -> list[Violation]:
    rules = DEFAULT_RULES._replace(declared=True, **kwargs)  # type: ignore[arg-type]
    return list(validate(ast.parse(source), rules))


def test_a_literal_needs_nothing_but_the_core() -> None:
    assert not _check("1", syntax=_syntax())


def test_arithmetic_is_refused_without_its_group() -> None:
    violations = _check("1 + 1", syntax=_syntax())
    assert len(violations) == 1
    assert "BinOp" in violations[0].message
    assert "eval-syntax=arith" in violations[0].remedy


def test_arithmetic_passes_with_its_group() -> None:
    assert not _check("1 + 1", syntax=_syntax("arith"))


@pytest.mark.parametrize(
    "group,source",
    [
        ("arith", "1 + 1"),
        ("compare", "1 < 2"),
        ("conditional", "1 if True else 2"),
        ("loop", "for i in ():\n    pass"),
        ("comprehension", "[x for x in ()]"),
        ("assign", "x = 1"),
        ("func", "def f():\n    return 1"),
        ("class", "class C:\n    pass"),
        ("exception", "try:\n    pass\nexcept ValueError:\n    pass"),
        ("context", "with open() as f:\n    pass"),
        ("subscript", "x[0]"),
        ("fstring", 'f"{x}"'),
        ("yield", "def f():\n    yield 1"),
    ],
)
def test_each_group_gates_its_own_syntax(group: str, source: str) -> None:
    """Refused without the group, accepted with it."""
    closed = _check(source, syntax=_syntax(), call=_names("open"), attribute=_names("x"))
    assert closed, f"{group} passed without its group"
    opened = _check(
        source,
        syntax=_syntax(group, "func", "assign", "loop"),
        call=_names("open"),
        attribute=_names("x"),
    )
    assert not [v for v in opened if "is not allowed" in v.message]


def test_async_is_neither_privileged_nor_special_cased() -> None:
    source = "async def f():\n    await g()"
    assert _check(source, syntax=_syntax("func"), call=_names("g"))
    assert not _check(source, syntax=_syntax("func", "async"), call=_names("g"))


def test_every_violation_is_reported_not_only_the_first() -> None:
    source = "while True:\n    import os\n    x = ().__class__"
    violations = _check(source, syntax=_syntax("assign"))
    messages = " ".join(v.message for v in violations)
    assert "While" in messages
    assert "os" in messages
    assert "__class__" in messages
    assert len(violations) >= 3


def test_an_import_outside_the_rule_is_refused() -> None:
    violations = _check("import os", syntax=_syntax("import"))
    assert len(violations) == 1
    assert "eval-import=os" in violations[0].remedy


def test_a_declared_import_passes() -> None:
    assert not _check("import json", syntax=_syntax("import"), imports=_names("json"))


def test_a_from_import_is_checked_on_its_module() -> None:
    assert not _check("from json import loads", syntax=_syntax("import"), imports=_names("json"))
    assert _check("from os import path", syntax=_syntax("import"), imports=_names("json"))


def test_a_dunder_attribute_is_refused_outside_eval_magic() -> None:
    violations = _check("x.__class__", syntax=_syntax(), attribute=_names("y"))
    assert len(violations) == 1
    assert "eval-magic=__class__" in violations[0].remedy


def test_a_dunder_identifier_is_refused_outside_eval_magic() -> None:
    assert _check("__builtins__", syntax=_syntax())


def test_a_declared_dunder_passes() -> None:
    assert not _check("x.__name__", syntax=_syntax(), magic=_names("__name__"))


def test_a_call_on_an_undeclared_name_is_refused() -> None:
    violations = _check("len([1])", syntax=_syntax())
    assert len(violations) == 1
    assert "eval-call=len" in violations[0].remedy


def test_a_call_on_a_declared_name_passes() -> None:
    assert not _check("len([1])", syntax=_syntax(), call=_names("len"))


def test_a_method_call_is_not_a_name_call() -> None:
    """Call.func is an Attribute here, so eval-attribute owns the decision."""
    assert not _check('"ab".split()', syntax=_syntax(), attribute=_names("split"))


def test_the_reserved_prefix_is_refused_as_an_identifier() -> None:
    violations = _check("__sb_tick__ = 1", syntax=_syntax("assign"))
    assert len(violations) == 1
    assert RESERVED_PREFIX in violations[0].message


def test_the_reserved_prefix_is_refused_as_an_attribute() -> None:
    assert _check("x.__sb_getattr__", syntax=_syntax(), magic=_names("__sb_getattr__"))


def test_an_attribute_store_is_refused() -> None:
    violations = _check("x.attr = 1", syntax=_syntax("assign"), attribute=_names("attr"))
    assert len(violations) == 1
    assert "Store" in violations[0].message or "assign" in violations[0].message


def test_an_attribute_delete_is_refused() -> None:
    assert _check("del x.attr", syntax=_syntax("assign"), attribute=_names("attr"))


def test_the_node_count_is_bounded() -> None:
    source = "[" + ", ".join("1" for _ in range(50)) + "]"
    violations = _check(source, syntax=_syntax(), max_nodes=10)
    assert any("eval-max-nodes" in v.remedy for v in violations)


def test_the_static_nesting_is_bounded() -> None:
    source = "[" * 30 + "]" * 30
    violations = _check(source, syntax=_syntax(), max_depth=5)
    assert any("eval-max-depth" in v.remedy for v in violations)


def test_the_report_is_exhaustive_actionable_and_honest() -> None:
    source = "while True:\n    import os\n    x = ().__class__\n"
    violations = _check(source, syntax=_syntax("assign"))
    report = render_report("<eval:llm>", source, violations)
    # Deliberately not a hardcoded count: `import os` alone yields both an
    # `Import` node violation and an `alias` one, so any literal here tracks the
    # grammar rather than the report. `render_report` builds this header from
    # `len(violations)`, so the line below checks the shape, not the total --
    # what this test actually pins is the four asserts that follow.
    assert f"{len(violations)} rules violated in <eval:llm>" in report
    assert "eval-syntax=loop" in report
    assert "eval-import=os" in report
    assert "eval-magic=__class__" in report
    assert "^" in report
    assert "⚠" in report


def test_raise_if_rejected_carries_the_syntax_error_fields() -> None:
    source = "while True:\n    pass\n"
    violations = _check(source, syntax=_syntax())
    with pytest.raises(EvalSyntaxRejected) as caught:
        raise_if_rejected("<eval>", source, violations)
    assert caught.value.lineno == 1
    assert caught.value.text == "while True:"
    assert caught.value.violations


def test_the_exception_carries_one_block_per_violation() -> None:
    """Not the whole report as a single element (the Task 1 contract)."""
    source = "while True:\n    import os\n    x = ().__class__\n"
    violations = _check(source, syntax=_syntax("assign"))
    with pytest.raises(EvalSyntaxRejected) as caught:
        raise_if_rejected("<eval>", source, violations)
    assert len(caught.value.violations) == len(violations)
    assert all("line " in block for block in caught.value.violations)


def test_raise_if_rejected_is_a_no_op_without_violations() -> None:
    raise_if_rejected("<eval>", "1", [])
