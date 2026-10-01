# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Hardening of the eval() guard: sensitive builtins, format, lambda depth.

Each test drives a payload that bypassed an eval-* rule before the guard
routed the sensitive builtins and the format templates through the same
runtime check as dotted attribute access, and bracketed lambdas the way
functions already were.
"""

import logging
import string
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalInterrupted, RuleEvalPermissionError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, SYNTAX_GROUPS, NameSet, parse_rules
from pysandboxes.guard_eval import _deactivate_guard_eval, activate_guard, guarded_eval, patch_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLine


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _syntax(*groups: str) -> NameSet:
    nodes = set(CORE_NODES)
    for group in groups:
        nodes.update(SYNTAX_GROUPS[group])
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _activate(**kwargs: object) -> None:
    kwargs.setdefault("syntax", _syntax())  # CORE_NODES, else every node is refused
    activate_guard(ImmutableDict({"": DEFAULT_RULES._replace(declared=True, **kwargs)}))  # type: ignore[arg-type]


class _Box:
    pass


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    _deactivate_guard_eval()


# ---------------------------------------------------------------- getattr shim
def test_getattr_builtin_is_routed_through_the_magic_check() -> None:
    _activate(call=_names("getattr"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("getattr((), '__class__')")
    assert caught.value.target == "__class__"


def test_getattr_builtin_cannot_reach_a_frame_capture_attribute() -> None:
    _activate(syntax=_syntax("comprehension"), call=_names("getattr"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("getattr(getattr((i for i in [1]), 'gi_frame'), 'f_globals')")
    assert caught.value.target in ("gi_frame", "f_globals")


def test_getattr_builtin_honours_a_granted_name_and_default() -> None:
    _activate(call=_names("getattr"), attribute=_names("zzz"))
    assert guarded_eval("getattr([], 'zzz', 99)") == 99


# ---------------------------------------------------------------- setattr/vars
def test_setattr_builtin_is_refused_like_a_store_attribute() -> None:
    _activate(call=_names("setattr"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("setattr(o, 'x', 7)", names={"o": _Box()})


def test_vars_builtin_is_gated_by_the_dunder_dict_rule() -> None:
    _activate(call=_names("vars"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("vars(o)", names={"o": _Box()})
    assert caught.value.target == "__dict__"


def test_vars_without_argument_is_refused() -> None:
    _activate(call=_names("vars"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("vars()")


# ---------------------------------------------------------------- type/globals
def test_type_one_argument_is_allowed() -> None:
    _activate(call=_names("type"))
    assert guarded_eval("type(())") is tuple


def test_type_class_factory_is_refused() -> None:
    _activate(syntax=_syntax(), call=_names("type"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("type('X', (), {})")


def test_globals_builtin_is_refused() -> None:
    _activate(call=_names("globals"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("globals()")


def test_breakpoint_builtin_is_refused() -> None:
    _activate(call=_names("breakpoint"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("breakpoint()")


# ------------------------------------------------------------------ str.format
def test_format_reaching_a_dunder_is_refused_at_runtime() -> None:
    _activate(attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("'{0.__class__}'.format(())")
    assert caught.value.target == "__class__"


def test_format_over_data_still_works() -> None:
    _activate(attribute=_names("format"))
    assert guarded_eval("'{0}-{1[0]}'.format(5, (7,))") == "5-7"


def test_format_nested_spec_field_is_validated() -> None:
    _activate(syntax=_syntax(), attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("'{0:{1.__class__}}'.format(3, 4)")


def test_unbound_str_format_on_the_class_is_validated() -> None:
    _activate(call=_names("str"), attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("str.format('{0.__class__}', ())")
    assert caught.value.target == "__class__"


def test_unbound_str_format_reached_through_type_is_validated() -> None:
    _activate(call=_names("type"), attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("type('').format('{0.__class__}', ())")
    assert caught.value.target == "__class__"


# ----------------------------------------------------------- string.Formatter
class _LyingFormatter(string.Formatter):
    """Hands get_field a field its template never showed."""

    def parse(self, format_string: str) -> Iterator[tuple[str, str | None, str | None, str | None]]:
        yield "", "0.__class__", "", None


@pytest.fixture
def _patched_get_field(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = patch_rules(False)["string.Formatter.get_field"]
    monkeypatch.setattr(string.Formatter, "get_field", factory(string.Formatter.get_field))


@pytest.mark.usefixtures("_patched_get_field")
@pytest.mark.parametrize(
    "source",
    [
        "F.format('{0.__class__.__base__}', ())",
        "F.vformat('{0.__class__}', ((),), {})",
        "F.get_field('0.__class__', ((),), {})",
    ],
)
def test_string_formatter_fields_are_validated(source: str) -> None:
    _activate(attribute=_names("format", "vformat", "get_field"))
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval(source, names={"F": string.Formatter()})
    assert caught.value.target == "__class__"


@pytest.mark.usefixtures("_patched_get_field")
def test_string_formatter_is_checked_where_the_field_is_read_not_where_it_is_parsed() -> None:
    _activate(attribute=_names("format"))
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("F.format('plain', ())", names={"F": _LyingFormatter()})


@pytest.mark.usefixtures("_patched_get_field")
def test_string_formatter_keeps_a_granted_attribute() -> None:
    _activate(attribute=_names("format", "real"))
    assert guarded_eval("F.format('{0.real}', 5)", names={"F": string.Formatter()}) == "5"


@pytest.mark.usefixtures("_patched_get_field")
def test_string_formatter_is_untouched_outside_an_evaluation() -> None:
    _activate(attribute=_names("format"))
    assert string.Formatter().format("{0.__class__.__name__}", ()) == "tuple"


# --------------------------------------------------------------- lambda depth
def test_lambda_recursion_is_bounded_by_max_call_depth() -> None:
    _activate(syntax=_syntax("func"), call=_names("f", "g"), max_call_depth=5, timeout=3.0)
    with pytest.raises(EvalInterrupted) as caught:
        guarded_eval("(lambda g: g(g))(lambda f: f(f))")
    assert "eval-max-call-depth" in str(caught.value)


# ------------------------------------------------------ eval-call warning
def _lines(*rules: str) -> list[ConfigLine]:
    return [ConfigLine(r, Path("profile"), i + 1) for i, r in enumerate(rules)]


def test_eval_call_on_a_builtin_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_rules(_lines("eval-call=len"), [])
    assert any("eval-call" in r.message and "len" in r.message for r in caplog.records)


def test_eval_call_on_a_capability_builtin_warns_stronger(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_rules(_lines("eval-call=getattr"), [])
    assert any("getattr" in r.message for r in caplog.records)
