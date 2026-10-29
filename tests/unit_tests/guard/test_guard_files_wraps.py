# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Every file guard replaces a stdlib callable by a wrapper that keeps its identity and hands no original back."""

import importlib
import inspect
import os
from typing import Any

import pytest

from pysandboxes import guard_files


def _original(qualname: str) -> Any:
    module_name, _, attribute_path = qualname.partition(".")
    owner: Any = importlib.import_module(module_name)
    for node in attribute_path.split("."):
        owner = getattr(owner, node)
    return owner


def _patched() -> list[tuple[str, Any]]:
    found = []
    for qualname, factory in guard_files.patch_rules(learn=False).items():
        try:
            found.append((qualname, (_original(qualname), factory)))
        except (ImportError, AttributeError):
            continue
    return found


def _a_user_callback(*args: Any) -> None:
    """Stands for an ``ignore=`` function."""


@pytest.mark.parametrize(
    ("factory", "original"),
    [
        (guard_files._wrap_user_callback, _a_user_callback),
        (guard_files._wrap_os_path_realpath, os.path.realpath),
    ],
)
def test_a_wrapper_outside_the_patch_table_keeps_the_name_of_what_it_wraps(factory: Any, original: Any) -> None:
    replacement = factory(original)

    assert not hasattr(replacement, "__wrapped__")
    assert replacement.__name__ == original.__name__
    assert replacement.__doc__ == original.__doc__


@pytest.mark.parametrize(("qualname", "pair"), _patched(), ids=lambda value: value if isinstance(value, str) else "")
def test_a_guard_keeps_the_name_of_what_it_replaces_and_hides_the_original(qualname: str, pair: Any) -> None:
    original, factory = pair

    replacement = factory(original)

    assert not hasattr(replacement, "__wrapped__")
    assert replacement.__name__ == getattr(original, "__name__", replacement.__name__)
    if inspect.isroutine(original) and not isinstance(original, type):
        assert replacement.__doc__ == original.__doc__
