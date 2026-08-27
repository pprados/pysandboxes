# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The framework's own dynamic-code call sites stay reachable once armed."""

import builtins
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.guard_api import _deactivate_guard_api, activate_guard
from pysandboxes.lifecycle import arm
from pysandboxes.guard_eval import _deactivate_guard_eval, patch_rules
from pysandboxes.remote import python_in_sb


@pytest.fixture(autouse=True)
def _armed_and_undeclared() -> Iterator[None]:
    """Arm the guard with no eval-* key: the strictest configuration."""
    saved = {name: getattr(builtins, name) for name in ("eval", "exec", "compile")}
    activate_guard(())
    arm()
    for key, factory in patch_rules(False).items():
        name = key.split(".")[1]
        setattr(builtins, name, factory(saved[name]))
    yield
    for name, value in saved.items():
        setattr(builtins, name, value)
    _deactivate_guard_api()
    _deactivate_guard_eval()


def test_the_module_captured_the_raw_builtins() -> None:
    assert not getattr(python_in_sb._RAW_EXEC, "__pysandbox_eval__", False)
    assert not getattr(python_in_sb._RAW_EVAL, "__pysandbox_eval__", False)
    assert not getattr(python_in_sb._RAW_COMPILE, "__pysandbox_eval__", False)


def test_the_patched_builtin_refuses_without_an_eval_key() -> None:
    from pysandboxes.e import RuleApiPermissionError

    with pytest.raises(RuleApiPermissionError):
        builtins.exec("x = 1")


def test_the_raw_capture_still_runs_the_user_script() -> None:
    namespace: dict[str, object] = {}
    python_in_sb._RAW_EXEC("x = 41 + 1", namespace)
    assert namespace["x"] == 42


def test_raw_builtins_restores_the_trio_for_the_repl() -> None:
    with python_in_sb.raw_builtins():
        assert not getattr(builtins.exec, "__pysandbox_eval__", False)
        builtins.exec("x = 1")
    assert getattr(builtins.exec, "__pysandbox_eval__", False)


def test_raw_builtins_restores_the_patch_even_on_an_exception() -> None:
    with pytest.raises(ValueError):
        with python_in_sb.raw_builtins():
            raise ValueError("boom")
    assert getattr(builtins.exec, "__pysandbox_eval__", False)
