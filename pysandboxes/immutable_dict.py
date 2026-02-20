"""Immutable dictionary implementation for PySandboxes.

This module provides an immutable dictionary class that prevents modification
after creation. Used for security configurations and environment variables
where immutability ensures configuration integrity.
"""

import collections
from typing import (
    Any,
    Callable,
    Generic,
    Hashable,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    TypeVar,
    ValuesView,
    cast,
)

KeyType = TypeVar("KeyType", bound=Hashable)
ValueType = TypeVar("ValueType")


def _restore_pickle(
    data: dict[KeyType, ValueType]
) -> "ImmutableDict[KeyType,ValueType]":
    return ImmutableDict(data)


class ImmutableDict(
    tuple[tuple[KeyType, ...], tuple[ValueType, ...]],
    collections.abc.Mapping,
    Generic[KeyType, ValueType],
):
    """
    An immutable dictionary-like object built on a tuple of tuples.
    This class is compatible with the collections.abc.Mapping kind.
    """

    __slot__ = ()

    # construction accepts either a Mapping or an iterable of (key, value) pairs
    def __new__(
        cls,
        data: Mapping[KeyType, ValueType]| Iterable[tuple[KeyType, ValueType]],
    ) -> "ImmutableDict[KeyType, ValueType]":
        # Normalize incoming data to an iterable of pairs
        keys: tuple[KeyType, ...]
        values: tuple[ValueType, ...]
        if isinstance(data, ImmutableDict):
            keys = data._keys
            values = data._values
        else:
            if isinstance(data, Mapping):
                from pysandboxes.guard_envs import LearnEnviron

                # Hack to detect the learn phase.
                # We don't want to learn all keys
                if isinstance(data, LearnEnviron):
                    data = dict(data)
                keys = cast(tuple[KeyType, ...], tuple(data.keys()))
                values = cast(tuple[ValueType, ...], tuple(data.values()))
            else:
                # allow any iterable of (k, v) pairs
                items = tuple(data)

                # Build parallel tuples of keys and values
                keys = tuple(item[0] for item in items if item)
                values = tuple(item[1] if len(item) > 1 else None for item in items)

        # Create the tuple-subclass with two items: (keys, values)
        obj = tuple.__new__(cls, (keys, values))
        return obj

    def __reduce__(self) -> tuple[Callable[..., Any], tuple[Any, ...]]:
        return (_restore_pickle, (dict(self),))

    @property
    def _keys(self) -> tuple[KeyType, ...]:
        return tuple.__getitem__(self, 0)  # type: ignore[index]

    @property
    def _values(self) -> tuple[ValueType, ...]:
        return tuple.__getitem__(self, 1)  # type: ignore[index]

    # Mapping kind
    def __getitem__(self, key: KeyType) -> ValueType:  # type: ignore[override]
        try:
            idx = self._keys.index(key)
        except ValueError:
            raise KeyError(key)
        return cast(ValueType, self._values[idx])

    def __iter__(self) -> Iterator[KeyType]:  # type: ignore[override]
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __contains__(self, key: object) -> bool:
        try:
            self._keys.index(key)  # type: ignore[arg-type]
            return True
        except ValueError:
            return False

    def __repr__(self) -> str:
        return f"ImmutableDict({dict(zip(self._keys, self._values))})"

    # Keep Mapping's default .keys(), .items(), .values()
    def keys(self) -> KeysView[KeyType]:
        return Mapping.keys(self)

    def items(self) -> ItemsView[KeyType, ValueType]:
        return Mapping.items(self)

    def values(self) -> ValuesView[ValueType]:
        return Mapping.values(self)
