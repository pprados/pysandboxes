# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""One test per attack, blocked or not.

Two matrices. `BLOCKED` lists escape attempts the guard must refuse: reaching
an object, a frame, a module or the host through any syntax. `RUNS` lists what
the guard deliberately lets through -- the calculator's legitimate work, and
the denial-of-service payloads it documents as out of reach of an AST-level
guard (a C loop, an allocation outside `+`/`*`/`**`), guaranteed only by the OS
layer. A payload moving between the two matrices is a real change in the
contract, which is why every one is pinned here.
"""

import sys
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalInterrupted, EvalSyntaxRejected, RuleEvalPermissionError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, SYNTAX_GROUPS, NameSet
from pysandboxes.guard_eval import _deactivate_guard_eval, activate_guard, guarded_eval
from pysandboxes.immutable_dict import ImmutableDict

_REFUSALS = (EvalSyntaxRejected, RuleEvalPermissionError, EvalInterrupted, NameError)


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _syntax(*groups: str) -> NameSet:
    nodes = set(CORE_NODES)
    for group in groups:
        nodes.update(SYNTAX_GROUPS[group])
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _rules(**kwargs: Any) -> None:
    kwargs.setdefault("syntax", _syntax())
    activate_guard(ImmutableDict({"": DEFAULT_RULES._replace(declared=True, **kwargs)}))  # type: ignore[arg-type]


def _box() -> object:
    return type("B", (), {})()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    _deactivate_guard_eval()


# ------------------------------------------------------------------ blocked
# id, source, config, mode, names
BLOCKED: list[tuple[str, str, dict[str, Any], str, dict[str, Any] | None]] = [
    ("getattr_to_magic", "getattr((), '__class__')", dict(call=_names("getattr")), "eval", None),
    (
        "getattr_to_frame",
        "getattr(getattr((i for i in [1]), 'gi_frame'), 'f_globals')",
        dict(syntax=_syntax("comprehension"), call=_names("getattr")),
        "eval",
        None,
    ),
    (
        "getattr_subclasses_to_popen",
        "[c for c in getattr(getattr(getattr((), '__class__'), '__base__'), '__subclasses__')()"
        " if getattr(c, '__name__') == 'Popen']",
        dict(syntax=_syntax("comprehension", "compare"), call=_names("getattr", "list")),
        "eval",
        None,
    ),
    ("getattr_default_on_refused_name", "getattr((), '__class__', 'x')", dict(call=_names("getattr")), "eval", None),
    ("setattr", "setattr(o, 'x', 7)", dict(call=_names("setattr")), "eval", {"o": _box()}),
    ("delattr", "delattr(o, 'x')", dict(call=_names("delattr")), "eval", {"o": _box()}),
    ("vars", "vars(o)", dict(call=_names("vars")), "eval", {"o": _box()}),
    ("vars_no_arg", "vars()", dict(call=_names("vars")), "eval", None),
    ("type_class_factory", "type('X', (), {})", dict(call=_names("type")), "eval", None),
    ("globals", "globals()", dict(call=_names("globals")), "eval", None),
    ("breakpoint", "breakpoint()", dict(call=_names("breakpoint")), "eval", None),
    ("dir_no_arg", "dir()", dict(call=_names("dir")), "eval", None),
    ("dotted_dunder", "().__class__", dict(), "eval", None),
    ("gi_frame_dot", "(i for i in ()).gi_frame", dict(syntax=_syntax("comprehension")), "eval", None),
    ("format_instance_dunder", "'{0.__class__}'.format(())", dict(attribute=_names("format")), "eval", None),
    (
        "format_class_unbound",
        "str.format('{0.__class__}', ())",
        dict(call=_names("str"), attribute=_names("format")),
        "eval",
        None,
    ),
    (
        "format_via_type",
        "type('').format('{0.__class__}', ())",
        dict(call=_names("type"), attribute=_names("format")),
        "eval",
        None,
    ),
    ("format_map_dunder", "'{0.__class__}'.format_map([()])", dict(attribute=_names("format_map")), "eval", None),
    (
        "format_nested_spec",
        "'{0:{1.__class__}}'.format(3, 4)",
        dict(attribute=_names("format")),
        "eval",
        None,
    ),
    (
        "lambda_recursion",
        "(lambda g: g(g))(lambda f: f(f))",
        dict(syntax=_syntax("func"), call=_names("f", "g"), max_call_depth=5, timeout=3.0),
        "eval",
        None,
    ),
    (
        "def_recursion",
        "def f(n):\n return f(n + 1)\nf(0)",
        dict(syntax=_syntax("func", "arith"), call=_names("f"), max_call_depth=5, timeout=3.0),
        "exec",
        None,
    ),
    (
        "generator_recursion",
        "def g(n):\n yield from g(n + 1)\n yield n\nlist(g(0))",
        dict(
            syntax=_syntax("func", "yield", "comprehension", "arith"),
            call=_names("g", "list"),
            max_call_depth=5,
            timeout=3.0,
        ),
        "exec",
        None,
    ),
    (
        "comprehension_iteration_budget",
        "[0 for _ in range(10**9)]",
        dict(syntax=_syntax("comprehension", "arith"), call=_names("range"), max_iterations=1000),
        "eval",
        None,
    ),
    (
        "pow_allocation",
        "2 ** 80000",
        dict(syntax=_syntax("arith"), max_alloc=1000),
        "eval",
        None,
    ),
    ("reserved_helper_name", "__sb_getattr__((), 'x')", dict(call=_names("getattr")), "eval", None),
    (
        "lambda_closure",
        "(lambda f: f.__closure__)(lambda: 0)",
        dict(syntax=_syntax("func"), call=_names("f")),
        "eval",
        None,
    ),
    ("import_statement", "import os", dict(syntax=_syntax("import")), "exec", None),
    ("fstring_attribute", "f'{ ().__class__ }'", dict(syntax=_syntax("fstring")), "eval", None),
    *(
        [("tstring_attribute", "t'{ ().__class__ }'", dict(syntax=_syntax("tstring")), "eval", None)]
        if sys.version_info >= (3, 14)
        else []
    ),
    (
        "type_mro_hop_to_subclasses",
        "getattr(type(()).mro()[1], '__subclasses__')",
        dict(syntax=_syntax("subscript"), call=_names("type", "getattr"), attribute=_names("mro")),
        "eval",
        None,
    ),
]


@pytest.mark.parametrize("source, config, mode, names", [pytest.param(s, c, m, n, id=i) for i, s, c, m, n in BLOCKED])
def test_attack_is_blocked(source: str, config: dict[str, Any], mode: str, names: dict[str, Any] | None) -> None:
    _rules(**config)
    with pytest.raises(_REFUSALS):
        guarded_eval(source, mode=mode, names=names)


# --------------------------------------------------------------------- runs
# id, source, config, expected, mode. Two families: the calculator's own work,
# and denial-of-service payloads documented as out of reach of the guard.
RUNS: list[tuple[str, str, dict[str, Any], Any, str]] = [
    # legitimate sub-language
    ("arithmetic", "2 + 3 * 4", dict(syntax=_syntax("arith")), 14, "eval"),
    (
        "comprehension",
        "[x * 2 for x in range(3)]",
        dict(syntax=_syntax("comprehension", "arith"), call=_names("range")),
        [0, 2, 4],
        "eval",
    ),
    ("type_one_arg", "type(())", dict(call=_names("type")), tuple, "eval"),
    ("format_over_data", "'{0}-{1[0]}'.format(5, (7,))", dict(attribute=_names("format")), "5-7", "eval"),
    ("str_method", "'ab'.upper()", dict(attribute=_names("upper")), "AB", "eval"),
    # denial of service: documented limits, guaranteed only by the OS layer
    (
        "dos_c_loop_no_tick",
        "sum(range(2000))",
        dict(syntax=_syntax("arith"), call=_names("sum", "range"), max_iterations=100, timeout=3.0),
        1999000,
        "eval",
    ),
    (
        "dos_bytes_allocation",
        "len(bytes(5000))",
        dict(syntax=_syntax("arith"), call=_names("bytes", "len"), max_alloc=100),
        5000,
        "eval",
    ),
]


@pytest.mark.parametrize("source, config, expected, mode", [pytest.param(s, c, e, m, id=i) for i, s, c, e, m in RUNS])
def test_payload_runs(source: str, config: dict[str, Any], expected: Any, mode: str) -> None:
    _rules(**config)
    assert guarded_eval(source, mode=mode) == expected
