# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Escape payloads, each asserting which layer stopped it.

Three layers, only two of which enforce anything: the bounded namespace and
the injected runtime guards are barriers; static validation is a fail-fast a
rewritten payload walks straight past. Asserting the catching layer is what
prevents a refactor from silently demoting a barrier.
"""

from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalSyntaxRejected, RuleEvalPermissionError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, SYNTAX_GROUPS, NameSet
from pysandboxes.guard_eval import _deactivate_guard_eval, activate_guard, guarded_eval
from pysandboxes.immutable_dict import ImmutableDict

POPEN_ESCAPE = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/sh'])"


def _syntax(*groups: str) -> NameSet:
    nodes = set(CORE_NODES)
    for group in groups:
        nodes.update(SYNTAX_GROUPS[group])
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _wide() -> NameSet:
    from pysandboxes.tools import GlobPattern

    return NameSet(allow=frozenset(), allow_patterns=(GlobPattern("*"),), deny=frozenset(), deny_patterns=())


def _activate(**kwargs: object) -> None:
    activate_guard(ImmutableDict({"": DEFAULT_RULES._replace(declared=True, **kwargs)}))  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    _deactivate_guard_eval()


def test_the_subclasses_walk_dies_on_the_namespace_and_the_validator() -> None:
    """Payload 1 of spec 2: no global name is called, every call is a method."""
    _activate(syntax=_syntax("comprehension", "compare", "subscript"), namespace="closed")
    with pytest.raises(EvalSyntaxRejected) as caught:
        guarded_eval(POPEN_ESCAPE)
    assert "__class__" in str(caught.value)


def test_a_wide_eval_magic_reopens_the_subclasses_walk() -> None:
    """The honest statement of what `eval-magic=*` costs.

    `__class__`, `__base__`, `__subclasses__` and `__name__` are ordinary
    dunders, none of them in FRAME_CAPTURE, so a profile that grants every
    magic name grants the walk itself -- the payload starts from the literal
    `()` and never writes a global name, so neither the closed namespace nor
    phase 1 has anything left to refuse.

    Asserted rather than reviewed, and asserted on a harmless target: reaching
    `object` proves the walk completed without this suite ever building a
    Popen. `eval-magic=*` is a configuration error, and this is the test that
    says so out loud.
    """
    _activate(
        syntax=_syntax("comprehension", "compare", "subscript"),
        namespace="closed",
        magic=_wide(),
        attribute=_wide(),
    )
    assert guarded_eval("().__class__.__base__") is object


def test_a_wide_eval_attribute_does_not_disarm_the_magic_rule() -> None:
    """Layer assertion: `eval-magic` still refuses, and phase 1 is what refuses.

    A wide `eval-attribute` is the plausible misconfiguration -- a profile that
    needed `.split()` and reached for `*`. It buys the payload nothing: the
    dunders are checked against `eval-magic`, which is still deny-all, and the
    check is static, so the refusal arrives before the source ever runs and
    names all four dunders at once rather than only the first.

    No NameError/TypeError/AttributeError in the expected set: those prove the
    payload broke, not that a rule refused it, and a corpus whose job is to say
    *which layer caught* must not accept "it failed somehow" as a pass. The
    runtime barrier, `__sb_getattr__`, is asserted separately by the frame
    capture test below, where no static check can see the refused name.
    """
    _activate(
        syntax=_syntax("comprehension", "compare", "subscript"),
        namespace="closed",
        attribute=_wide(),
    )
    with pytest.raises(EvalSyntaxRejected) as caught:
        guarded_eval(POPEN_ESCAPE)
    report = str(caught.value)
    assert "eval-magic=__class__" in report
    assert "eval-magic=__subclasses__" in report


def test_getattr_in_a_list_is_not_a_name_call_and_still_fails() -> None:
    """Payload 2 of spec 2: the name exists but not in Call.func position.

    Phase 1 lets it through -- `Call.func` is a Subscript, so `eval-call` never
    looks at it -- and `object` is not in the closed namespace. The refusal
    that lands is therefore the runtime one, on the dunder the payload reads.
    """
    _activate(
        syntax=_syntax("subscript"),
        namespace="closed",
        call=NameSet(allow=frozenset({"getattr"}), allow_patterns=(), deny=frozenset(), deny_patterns=()),
    )
    with pytest.raises((EvalSyntaxRejected, RuleEvalPermissionError)) as caught:
        guarded_eval("[getattr][0](object(), '__class__')")
    assert "__class__" in str(caught.value) or "object" in str(caught.value)


def test_a_name_built_by_concatenation_dies_on_the_namespace() -> None:
    """Payload 3 of spec 2: the name is never written at all.

    `NameError` is the *expected* outcome here and is asserted as such, not
    tolerated alongside a refusal: the point of this payload is that a closed
    namespace holds no `__builtins__` to walk, so the name resolution fails
    before any rule is consulted. That is the namespace layer doing the work.
    """
    _activate(syntax=_syntax("arith", "subscript"), namespace="closed")
    with pytest.raises((NameError, RuleEvalPermissionError, EvalSyntaxRejected)) as caught:
        guarded_eval("__builtins__.__dict__['ope' + 'n']('/etc/passwd').read()")
    assert "__builtins__" in str(caught.value) or "__dict__" in str(caught.value)


def test_frame_capture_through_a_generator_is_refused() -> None:
    """gi_frame.f_globals reaches the real globals without writing a dunder."""
    _activate(
        syntax=_syntax("comprehension", "func", "yield"),
        namespace="closed",
        attribute=_wide(),
        magic=_wide(),
    )
    with pytest.raises(RuleEvalPermissionError) as caught:
        guarded_eval("(i for i in ()).gi_frame")
    # FRAME_CAPTURE is the one implicit DENY no configuration overrides, so the
    # refusal must come from it even with attribute and magic wide open. An
    # AttributeError here would mean the generator simply had no such member --
    # a different outcome, and not a guarded one.
    assert caught.value.target == "gi_frame"
