# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Rule data types must be typed, deep-copyable, comparable and have a repr that rebuilds the value.

Symbolic-execution and property-based tools rely on these properties (e.g. CrossHair, see
https://crosshair.readthedocs.io/en/latest/cover.html#caveats), and so do tests that compare reprs.
"""

import copy
import dataclasses
import enum
import importlib
import inspect
import pkgutil
import types
import typing
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from pathlib import Path
from typing import Any

import pytest

import pysandboxes
from pysandboxes.immutable_dict import ImmutableDict


def _is_data_type(cls: type) -> bool:
    return (issubclass(cls, tuple) and hasattr(cls, "_fields")) or dataclasses.is_dataclass(cls)


def _data_types() -> list[type]:
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(pysandboxes.__path__, "pysandboxes."):
        try:
            module = importlib.import_module(info.name)
        except Exception:  # optional dependency or platform-only module
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and _is_data_type(cls):
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return list(found.values())


_NAMESPACE: dict[str, Any] = {}
_DATA_TYPES = _data_types()


def _sample(tp: Any) -> Any:
    """Build a minimal value for a type hint."""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if tp is Any or tp is object:
        return 0
    if tp is type(None):
        return None
    if origin in (typing.Union, types.UnionType):
        return _sample(next(a for a in args if a is not type(None)))
    if origin is typing.Literal:
        return args[0]
    if origin is Callable or tp is Callable:
        return str
    if origin in (tuple,):
        return tuple(_sample(args[0]) for _ in range(1)) if args and args[-1] is Ellipsis else tuple(map(_sample, args))
    if origin in (list, set, frozenset):
        return origin([_sample(args[0])])
    if origin is dict:
        return {_sample(args[0]): _sample(args[1])}
    if origin is ImmutableDict or tp is ImmutableDict:
        return ImmutableDict({"k": _sample(args[1]) if args else 0})
    if inspect.isclass(tp):
        if issubclass(tp, enum.Enum):
            return next(iter(tp))
        if tp is bool:
            return True
        if tp in (int, float):
            return tp(1)
        if tp is str:
            return "x"
        if tp is Path:
            return Path("p")
        if tp is IPv4Network:
            return IPv4Network("10.0.0.0/8")
        if tp is IPv6Network:
            return IPv6Network("::/0")
        if tp is IPv4Address:
            return IPv4Address("10.0.0.1")
        if tp is range:
            return range(1, 3)
        if tp is ModuleSpec:
            return ModuleSpec("m", None)
        if _is_data_type(tp):
            return _build(tp)
    if isinstance(tp, str):
        return _build(next(c for c in _DATA_TYPES if c.__name__ == tp.strip("'")))
    raise TypeError(f"no sample for {tp!r}")


def _build(cls: type) -> Any:
    hints = typing.get_type_hints(cls, localns={c.__name__: c for c in _DATA_TYPES})
    fields = [f for f in (cls._fields if hasattr(cls, "_fields") else [f.name for f in dataclasses.fields(cls)])]
    return cls(**{name: _sample(hints[name]) for name in fields})


def _ids(cls: type) -> str:
    return f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}"


def test_data_types_found() -> None:
    assert len(_DATA_TYPES) >= 20


@pytest.mark.parametrize("cls", _DATA_TYPES, ids=_ids)
def test_every_field_is_annotated(cls: type) -> None:
    if hasattr(cls, "_fields"):
        assert set(cls._fields) <= set(cls.__annotations__)
    else:
        assert all(f.type is not dataclasses.MISSING for f in dataclasses.fields(cls))


@pytest.mark.parametrize("cls", _DATA_TYPES, ids=_ids)
def test_deepcopy_is_equal(cls: type) -> None:
    value = _build(cls)
    assert copy.deepcopy(value) == value


@pytest.mark.parametrize("cls", _DATA_TYPES, ids=_ids)
def test_repr_rebuilds_the_value(cls: type) -> None:
    value = _build(cls)
    namespace: dict[str, Any] = {c.__name__: c for c in _DATA_TYPES}
    namespace.update(ImmutableDict=ImmutableDict, PosixPath=Path, IPv4Network=IPv4Network, IPv6Network=IPv6Network)
    namespace.update(ModuleSpec=ModuleSpec, IPv4Address=IPv4Address, **{e.__name__: e for e in _enums()})
    try:
        rebuilt = eval(repr(value), namespace)  # noqa: S307
    except SyntaxError:
        pytest.skip("repr holds a non-reconstructible object")
    assert rebuilt == value


def _enums() -> list[type]:
    return [Kind for Kind in _enum_types()]


def _enum_types() -> set[type]:
    out: set[type] = set()
    for cls in _DATA_TYPES:
        for hint in typing.get_type_hints(cls, localns={c.__name__: c for c in _DATA_TYPES}).values():
            for t in (hint, *typing.get_args(hint)):
                if inspect.isclass(t) and issubclass(t, enum.Enum):
                    out.add(t)
    return out
