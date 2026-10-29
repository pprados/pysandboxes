# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Teach crosshair to build a ``pathlib.Path``: its constructor signature makes crosshair fail on any ``Path`` field.

A path is a fixed value: the contracts only check that it travels through a function unchanged, and ``Path`` refuses a
symbolic string.
"""

from pathlib import Path

from crosshair.core import SymbolicFactory, register_type


def _make_path(factory: SymbolicFactory) -> Path:
    return Path("config/.py-sandboxes")


register_type(Path, _make_path)
