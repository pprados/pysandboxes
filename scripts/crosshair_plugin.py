# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Teach crosshair to build the values it cannot build alone.

- ``pathlib.Path``: its constructor signature makes crosshair fail on any ``Path`` field. A path is a fixed value: the
  contracts only check that it travels through a function unchanged, and ``Path`` refuses a symbolic string.
- ``ImmutableDict``: crosshair fills the tuple subclass without going through ``__new__``, so it could build repeated
  keys, a state the class refuses. It is built from a symbolic ``dict`` instead.
"""

from pathlib import Path
from typing import Any

from crosshair.core import SymbolicFactory, register_type

from pysandboxes.immutable_dict import ImmutableDict as _ImmutableDict


def _make_path(factory: SymbolicFactory) -> Path:
    return Path("config/.py-sandboxes")


def _make_immutable_dict(factory: SymbolicFactory, key_type: type = int, value_type: type = int) -> Any:
    from pysandboxes.immutable_dict import ImmutableDict

    return ImmutableDict(factory(dict[key_type, value_type]))  # type: ignore[valid-type]


register_type(Path, _make_path)
register_type(_ImmutableDict, _make_immutable_dict)
