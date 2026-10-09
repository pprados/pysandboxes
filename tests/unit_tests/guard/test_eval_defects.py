# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import ast
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import guard_eval
from pysandboxes.e import EvalInterrupted, EvalSyntaxRejected, RuleApiPermissionError, RuleEvalPermissionError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, SYNTAX_GROUPS, NameSet, parse_rules
from pysandboxes.eval_transform import validate
from pysandboxes.guard_api import _deactivate_guard_api
from pysandboxes.guard_api import activate_guard as activate_api
from pysandboxes.guard_eval import (
    _deactivate_guard_eval,
    _wrap_compile,
    _wrap_eval_like,
    classify_context_value,
    guarded_eval,
    leaked_threads,
)
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.lifecycle import arm as arm_api
from pysandboxes.sb_types import ConfigLine


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _all_syntax() -> NameSet:
    nodes = set(CORE_NODES).union(*SYNTAX_GROUPS.values())
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _activate(**kwargs: Any) -> None:
    rules = DEFAULT_RULES._replace(declared=True, syntax=_all_syntax(), namespace="closed", **kwargs)
    guard_eval.activate_guard(ImmutableDict({"": rules}))


def _exec_namespace(source: str, names: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Run `source` in exec mode and return its namespace, to read what the evaluated code built itself."""
    rules = DEFAULT_RULES._replace(declared=True, syntax=_all_syntax(), namespace="closed", **kwargs)
    namespace = guard_eval.build_namespace(rules, caller_globals=None, names=names, from_wrapper=True)
    guard_eval.run_guarded(source, rules, mode="exec", namespace=namespace, source_ref="<test>")
    return namespace


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    _deactivate_guard_eval()
    _deactivate_guard_api()


@pytest.mark.parametrize(
    "source",
    [
        "def __sb_tick__():\n    pass",
        "class __sb_x:\n    pass",
        "lambda __sb_x: 1",
        "f(__sb_x=1)",
        "try:\n    pass\nexcept E as __sb_x:\n    pass",
        "def f():\n    global __sb_x",
        "match v:\n    case __sb_x:\n        pass",
        "match v:\n    case {**__sb_x}:\n        pass",
        "import m as __sb_x",
    ],
)
def test_every_bound_identifier_is_refused_the_reserved_prefix(source: str) -> None:
    rules = DEFAULT_RULES._replace(declared=True, syntax=_all_syntax(), call=_names("f"), imports=_names("m"))
    messages = [v.message for v in validate(ast.parse(source), rules)]
    assert any("reserved prefix" in message for message in messages), messages


def test_an_augmented_repetition_is_bounded_by_max_alloc() -> None:
    _activate(max_alloc=1000)
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        guarded_eval("a *= 10000", names={"a": [0]}, mode="exec")


def test_an_augmented_concatenation_is_bounded_by_max_alloc() -> None:
    _activate(max_alloc=1000)
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        guarded_eval("a += b", names={"a": [0] * 600, "b": [0] * 600}, mode="exec")


def test_an_augmented_assignment_still_works_in_place() -> None:
    shared = [1]
    _activate()
    guarded_eval("b = a\nb *= 2", names={"a": shared}, mode="exec")
    assert shared == [1, 1]


def test_an_augmented_subscript_evaluates_its_container_and_key_once() -> None:
    calls: list[int] = []

    def key() -> str:
        calls.append(1)
        return "k"

    _activate(call=_names("key"))
    namespace = _exec_namespace("d = {'k': [1]}\nd[key()] += [2]", {"key": key}, call=_names("key"))
    assert namespace["d"] == {"k": [1, 2]}
    assert calls == [1]


def test_an_augmented_slice_still_works() -> None:
    _activate()
    assert _exec_namespace("d = [1, 2, 3]\nd[0:2] *= 2")["d"] == [1, 2, 1, 2, 3]


def test_a_leaked_worker_that_finished_no_longer_counts() -> None:
    _activate(max_leaked_threads=1)
    finished = threading.Thread(target=lambda: None)
    finished.start()
    finished.join()
    guard_eval._leaked.append(finished)
    assert leaked_threads() == 0
    assert guarded_eval("1 + 1") == 2


def test_two_swaps_at_once_leave_the_patched_thread_primitive(monkeypatch: pytest.MonkeyPatch) -> None:
    name = next(iter(guard_eval._RAW_THREAD_PRIMITIVES))
    raw = guard_eval._RAW_THREAD_PRIMITIVES[name]

    def patched(*args: Any, **kwargs: Any) -> Any:
        return raw(*args, **kwargs)

    monkeypatch.setattr(threading, name, patched)
    second: list[threading.Thread] = []

    def fake_start(thread: threading.Thread) -> None:
        if thread.name == "first":
            # A second evaluation starts its thread while the first one holds the raw primitive.
            runner = threading.Thread(target=guard_eval._start_unguarded, args=(threading.Thread(name="second"),))
            runner.start()
            second.append(runner)
        else:
            time.sleep(0.2)

    monkeypatch.setattr(guard_eval, "_RAW_THREAD_START", fake_start)
    guard_eval._start_unguarded(threading.Thread(name="first"))
    second[0].join()
    assert getattr(threading, name) is patched


def _arm() -> None:
    activate_api(())
    arm_api()


def test_a_code_object_with_a_forged_eval_filename_is_refused() -> None:
    _arm()
    _activate()
    forged = guard_eval._RAW_COMPILE("1 + 1", f"{guard_eval.TAG_PREFIX}default>", "eval")
    patched_eval = _wrap_eval_like(eval, qualname="builtins.eval", mode="eval")
    with pytest.raises(RuleApiPermissionError, match="did not produce"):
        patched_eval(forged)


def test_a_code_object_from_guarded_compile_runs_under_the_budgets() -> None:
    _arm()
    _activate(max_iterations=10, timeout=30.0)
    code = _wrap_compile(compile)("while True:\n    pass", "<s>", "exec")
    patched_exec = _wrap_eval_like(exec, qualname="builtins.exec", mode="exec")
    with pytest.raises(EvalInterrupted, match="eval-max-iterations=10"):
        patched_exec(code)


def test_a_tree_from_guarded_compile_compiles_again() -> None:
    _arm()
    _activate()
    guarded_compile = _wrap_compile(compile)
    tree = guarded_compile("40 + 2", "<s>", "eval", ast.PyCF_ONLY_AST)
    assert isinstance(tree, ast.Expression)
    patched_eval = _wrap_eval_like(eval, qualname="builtins.eval", mode="eval")
    assert patched_eval(guarded_compile(tree, "<s>", "eval")) == 42


def test_a_compiled_source_that_overflows_the_parser_is_refused_not_raised() -> None:
    """Same `ast.parse` ceiling as `run_guarded`, reached through the `compile()` route.

    `RecursionError` on CPython's recursive-descent builds (3.11), `MemoryError`
    ("Parser stack overflowed") on the PEG parser (3.14 here); either way the
    guarded `compile()` must refuse it as `EvalSyntaxRejected`, not raise it raw.
    """
    _arm()
    _activate()
    guarded_compile = _wrap_compile(compile)
    with pytest.raises(EvalSyntaxRejected, match="eval-max-depth=parse"):
        guarded_compile("-" * 20000 + "1", "<s>", "eval")


def test_exec_without_namespace_does_not_rebind_the_caller_locals() -> None:
    patched_exec = _wrap_eval_like(exec, qualname="builtins.exec", mode="exec")

    def caller() -> int:
        x = 1
        patched_exec("x = 3")
        return x

    assert caller() == 1


def _nested_unary_minus(depth: int) -> ast.Expression:
    """Build `-(-(-...1...))`, `depth` levels deep, without going through `ast.parse`.

    `ast.parse` itself refuses a source nested this deep on some Python versions (its own
    C-level parser has a lower recursion ceiling than this library's own, Python-level guard),
    so the tree is built directly to exercise `validate()` regardless of that ceiling.
    """
    # No `ast.fix_missing_locations`: it walks the tree recursively and would hit the same
    # ceiling; `validate()` only reads `lineno`/`col_offset` through `getattr(..., 0)`.
    node: ast.expr = ast.Constant(value=1)
    for _ in range(depth):
        node = ast.UnaryOp(op=ast.USub(), operand=node)
    return ast.Expression(body=node)


def test_a_source_deeper_than_the_recursion_limit_is_refused_by_max_depth() -> None:
    tree = _nested_unary_minus(3000)
    violations = validate(tree, DEFAULT_RULES._replace(declared=True))
    assert [v.remedy.split("=")[0] for v in violations] == ["eval-max-depth"]


def test_a_max_depth_past_the_stack_still_refuses_instead_of_crashing() -> None:
    tree = _nested_unary_minus(sys.getrecursionlimit() * 3)
    violations = validate(tree, DEFAULT_RULES._replace(declared=True, max_depth=10**9))
    assert [v.remedy.split("=")[0] for v in violations] == ["eval-max-depth"]


@pytest.mark.parametrize("token", ["parse", "NodeVisitor", "Num"])
def test_eval_syntax_refuses_what_is_not_a_node(token: str) -> None:
    errors: list[Any] = []
    parse_rules([ConfigLine(f"eval-syntax={token}", Path(), 0)], errors)
    assert errors


@pytest.mark.parametrize("name", ["delattr", "hasattr"])
def test_a_builtin_parse_rules_reports_as_sensitive_is_a_strong_context_value(name: str) -> None:
    import builtins

    assert classify_context_value(getattr(builtins, name)) == "strong"


@pytest.mark.parametrize("source", ["a = 1 << 100000", "a = 1\na <<= 100000"])
def test_a_left_shift_is_bounded_by_max_alloc(source: str) -> None:
    _activate(max_alloc=1000)
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        guarded_eval(source, mode="exec")


def test_a_small_left_shift_still_works() -> None:
    _activate(max_alloc=1000)
    assert _exec_namespace("d = [1]\nd[0] <<= 3", max_alloc=1000)["d"] == [8]
    assert guarded_eval("d[0] << 1", names={"d": [8]}) == 16


@pytest.mark.parametrize(
    "source",
    [
        "'%0100000000d' % 1",
        "b'%.100000000f' % 1.0",
        "'%*d' % (100000000, 1)",
        "f'{1:0100000000d}'",
        "f'{1:{n}}'",
        "format(1, '0100000000d')",
        "'{:0100000000d}'.format(1)",
        "'{:{}}'.format(1, n)",
        "str.format('{:{}}', 1, n)",
    ],
)
def test_a_format_width_is_bounded_by_max_alloc(source: str) -> None:
    _activate(max_alloc=1000, call=_names("format", "str"), attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError, match="eval-max-alloc"):
        guarded_eval(source, names={"n": 100_000_000})


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("'%5d|%-3s' % (1, 'a')", "    1|a  "),
        ("f'{s!r:>6}|{n:{w}}'", "  'ab'|  7"),
        ("format(7, '03')", "007"),
        ("'{:>3}{}'.format(1, 2)", "  12"),
    ],
)
def test_a_narrow_format_still_works(source: str, expected: str) -> None:
    _activate(max_alloc=1000, call=_names("format"), attribute=_names("format"))
    assert guarded_eval(source, names={"s": "ab", "n": 7, "w": 3}) == expected


def test_a_format_spec_is_evaluated_once() -> None:
    calls: list[int] = []

    def width() -> int:
        calls.append(1)
        return 3

    _activate(call=_names("width"))
    assert guarded_eval("f'{1:{width()}}'", names={"width": width}) == "  1"
    assert calls == [1]
