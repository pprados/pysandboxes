# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Security proof tests for the dynamic-code guard (AREA D of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_eval_profile_escalation.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_eval_profile_escalation.py
"""

import builtins

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RuleEvalPermissionError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, NameSet
from pysandboxes.guard_api import _deactivate_guard_api
from pysandboxes.guard_api import activate_guard as activate_api
from pysandboxes.guard_eval import activate_guard, guarded_eval, patch_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.lifecycle import arm as arm_api


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _syntax(*names: str) -> NameSet:
    return NameSet(
        allow=frozenset(CORE_NODES) | frozenset(names), allow_patterns=(), deny=frozenset(), deny_patterns=()
    )


def test_security_nested_eval_cannot_escape_its_own_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """A named `eval-*` profile is a declared boundary: code `guarded_eval(src, profile="restricted")`
    runs should never reach more than that profile's own rules grant, whatever it does.

    `guard_eval._wrap_eval_like` resolves the rules for a *nested* call to the patched
    `builtins.eval`/`exec`/`compile` with ``rules = _profiles.get("")`` unconditionally
    (pysandboxes/guard_eval.py, inside `wrapper`) -- the default profile, never the profile
    the enclosing `guarded_eval()` call was running under. `eval-call=eval` is an ordinary,
    documented grant for a named profile (the parser even warns that it "widens the reachable
    surface", `eval_rules.py::_parse_list_value`), needed whenever the sub-language itself
    wants to invoke one more round of evaluation. The moment a profile grants it, any
    attribute, syntax or import restriction that profile declares stops applying to the
    nested call: the nested `eval()` is judged solely by whatever the *default* (``""``)
    profile allows, which an application typically keeps wide open for its own, separately
    trusted, uses of `eval`/`exec` elsewhere in the codebase.

    Here the default profile is given exactly one grant the "restricted" profile is denied
    (`eval-attribute=imag`), and "restricted" is given only `eval-call=eval`. Reading
    `(1).imag` straight under "restricted" is correctly refused. Reading the very same
    attribute through one level of nesting -- `eval('(1).imag')`, run under the very same
    "restricted" profile -- succeeds, because the nested call is secretly re-judged against
    the default profile instead.
    """
    _deactivate_guard_api()
    activate_api(())
    arm_api()
    default_rules = DEFAULT_RULES._replace(declared=True, syntax=_syntax(), attribute=_names("imag"))
    restricted_rules = DEFAULT_RULES._replace(declared=True, syntax=_syntax(), call=_names("eval"))
    activate_guard(ImmutableDict({"": default_rules, "restricted": restricted_rules}))
    # Simulates what `activate_sandboxes()` does process-wide: binds the guarded wrapper
    # under the real builtin name, so a nested `eval(...)` written inside evaluated source
    # resolves to it, exactly as `_builtins_from()` looks it up by `getattr(builtins, "eval")`.
    wrapped_eval = patch_rules(False)["builtins.eval"](builtins.eval)
    monkeypatch.setattr(builtins, "eval", wrapped_eval)

    # Control: the "restricted" profile refuses this attribute when asked directly.
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("(1).imag", profile="restricted")

    # Guarantee under test: the same profile governs code it runs, even one level through
    # a nested eval() call that profile itself explicitly granted.
    with pytest.raises(RuleEvalPermissionError):
        guarded_eval("eval('(1).imag')", profile="restricted")

    _deactivate_guard_api()


def test_a_nested_eval_still_runs_what_its_own_profile_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    _deactivate_guard_api()
    activate_api(())
    arm_api()
    default_rules = DEFAULT_RULES._replace(declared=True, syntax=_syntax())
    restricted_rules = DEFAULT_RULES._replace(
        declared=True, syntax=_syntax(), call=_names("eval"), attribute=_names("imag")
    )
    activate_guard(ImmutableDict({"": default_rules, "restricted": restricted_rules}))
    wrapped_eval = patch_rules(False)["builtins.eval"](builtins.eval)
    monkeypatch.setattr(builtins, "eval", wrapped_eval)

    assert guarded_eval("eval('(1).imag')", profile="restricted") == 0

    _deactivate_guard_api()
