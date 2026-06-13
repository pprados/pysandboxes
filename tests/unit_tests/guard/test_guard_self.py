# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``GuardModule``'s own logic, which had no test file at all.

The class is deliberately not wired into the sandbox pipeline yet, so these
tests cover what it does contain rather than any end-to-end property: a
guarded attribute must refuse assignment, and an unguarded one must not.
"""

from types import ModuleType

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RuleAttributeError
from pysandboxes.guard_self import GuardModule


def _guarded_module(*guarded: str) -> GuardModule:
    """Wrap a throwaway module, guarding the named attributes."""
    original = ModuleType("original")
    original.kept = "value"  # type: ignore[attr-defined]
    original.locked = "value"  # type: ignore[attr-defined]
    return GuardModule("original", _original=original, _guard_attributs=guarded)


def test_a_bare_construction_is_not_guarded() -> None:
    """Without the private keywords, the class hands back a plain module."""
    module = GuardModule("plain")

    assert type(module) is ModuleType
    module.anything = 1  # type: ignore[attr-defined]


def test_the_original_contents_are_copied() -> None:
    module = _guarded_module("locked")

    assert module.kept == "value"  # type: ignore[attr-defined]
    assert module.locked == "value"  # type: ignore[attr-defined]


def test_setting_a_guarded_attribute_is_refused() -> None:
    module = _guarded_module("locked")

    with pytest.raises(RuleAttributeError) as exc:
        module.locked = "replaced"  # type: ignore[attr-defined]

    assert "locked" in str(exc.value)
    assert module.locked == "value"  # type: ignore[attr-defined]


def test_setting_an_unguarded_attribute_is_allowed() -> None:
    """The guard names attributes one by one, it is not a freeze."""
    module = _guarded_module("locked")

    module.kept = "replaced"  # type: ignore[attr-defined]

    assert module.kept == "replaced"  # type: ignore[attr-defined]


def test_nothing_is_guarded_when_no_attribute_is_named() -> None:
    module = _guarded_module()

    module.locked = "replaced"  # type: ignore[attr-defined]

    assert module.locked == "replaced"  # type: ignore[attr-defined]
