# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Integrity of the guard_api registry.

These tests do not exercise behaviour. They assert that every registry
entry designates a real object on this platform, and that no guarded
object is reachable through a qualified name absent from the registry.
"""

import importlib
import os
from typing import Any

import pytest

from pysandboxes.guard_api import (
    OPTIONAL,
    SENSITIVE_API,
    all_qualnames,
    patch_rules,
    split_qualname,
)

# Low-level modules whose objects the high-level modules re-export.
ALIAS_SOURCES: tuple[tuple[str, str], ...] = (
    ("os", "nt" if os.name == "nt" else "posix"),
    ("signal", "_signal"),
    ("threading", "_thread"),
)


def _resolve(qualname: str) -> Any:
    module_name, attribute_path = split_qualname(qualname)
    obj: Any = importlib.import_module(module_name)
    for node in attribute_path.split("."):
        obj = getattr(obj, node)
    return obj


@pytest.mark.parametrize("qualname", all_qualnames())
def test_registry_entry_exists(qualname: str) -> None:
    """Every entry designates a real object, unless declared optional.

    An entry absent on this version or platform must be listed in
    OPTIONAL. That way a typo still fails while a version difference
    does not.
    """
    try:
        assert _resolve(qualname) is not None
    except (ImportError, AttributeError):
        assert qualname in OPTIONAL, (
            f"{qualname} does not resolve and is not in OPTIONAL: "
            "either it is a typo, or add it to OPTIONAL with the "
            "version or platform that justifies it"
        )


def test_the_windows_twins_are_registered() -> None:
    # On Windows `os.system is nt.system`, and subprocess reaches _winapi.CreateProcess:
    # with only the posix twins registered, `import nt; nt.system(...)` ran unguarded.
    assert {"nt.system", "nt.spawnv", "nt.kill", "os.startfile", "_winapi.CreateProcess"} <= set(all_qualnames())


@pytest.mark.parametrize(
    ("platform", "patched", "left_out"),
    [("win32", "nt.system", "os.fork"), ("linux", "os.fork", "nt.system")],
)
def test_each_platform_patches_only_its_own_entries(
    monkeypatch: pytest.MonkeyPatch, platform: str, patched: str, left_out: str
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    table = patch_rules(learn=False)
    assert patched in table
    assert left_out not in table


def test_optional_entries_are_registered() -> None:
    """OPTIONAL must not mention names outside the registry."""
    assert OPTIONAL <= set(all_qualnames())


def test_no_duplicate_entry() -> None:
    """A qualified name belongs to exactly one category."""
    seen: dict[str, str] = {}
    for category, qualnames in SENSITIVE_API.items():
        for qualname in qualnames:
            other = seen.get(qualname)
            message = f"{qualname} is in both {other} and {category}"
            assert qualname not in seen, message
            seen[qualname] = category


@pytest.mark.parametrize("high,low", ALIAS_SOURCES)
def test_no_uncovered_alias(high: str, low: str) -> None:
    """A guarded object must not be reachable by an unlisted name.

    ``os.system`` *is* ``posix.system``: patching the attribute on ``os``
    leaves ``posix.system`` untouched, so both names must be in the
    registry or the layer is bypassed.
    """
    registry = set(all_qualnames())
    high_mod = importlib.import_module(high)
    low_mod = importlib.import_module(low)
    uncovered: list[str] = []
    for qualname in sorted(registry):
        module_name, attribute_path = split_qualname(qualname)
        if module_name != high or "." in attribute_path:
            continue
        guarded = getattr(high_mod, attribute_path, None)
        twin = getattr(low_mod, attribute_path, None)
        if twin is not None and twin is guarded:
            alias = f"{low}.{attribute_path}"
            if alias not in registry:
                uncovered.append(alias)
    assert not uncovered, f"these aliases bypass the guard: {uncovered}"
