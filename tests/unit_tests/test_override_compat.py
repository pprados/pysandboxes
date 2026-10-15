# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`override_compat`: it finds `override` wherever the interpreter has it, and falls back to a no-op."""

import importlib.util
import sys
import types
import typing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest  # type: ignore[import-untyped]

import pysandboxes.override_compat as real_module


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("override_compat_copy", Path(real_module.__file__))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _marker(name: str) -> Any:
    def decorator(func: Any) -> Any:
        func.chosen_by = name
        return func

    return decorator


def test_typing_extensions_comes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("typing_extensions")
    fake.override = _marker("typing_extensions")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "typing_extensions", fake)
    monkeypatch.setattr(typing, "override", _marker("typing"), raising=False)

    module = _load()

    assert module.override(lambda: None).chosen_by == "typing_extensions"


def test_the_standard_library_comes_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "typing_extensions", None)
    monkeypatch.setattr(typing, "override", _marker("typing"), raising=False)

    module = _load()

    assert module.override(lambda: None).chosen_by == "typing"


def test_a_minimal_guest_gets_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "typing_extensions", None)
    monkeypatch.delattr(typing, "override", raising=False)

    module = _load()

    def method() -> int:
        return 3

    assert module.override(method) is method
    assert method() == 3


def test_only_override_is_exported() -> None:
    assert real_module.__all__ == ("override",)
