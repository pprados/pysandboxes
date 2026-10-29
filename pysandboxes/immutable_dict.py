# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Immutable dictionary implementation for PySandboxes.

This module provides an immutable dictionary class that prevents modification
after creation. Used for security configurations and environment variables
where immutability ensures configuration integrity.
"""

import collections.abc
import copy
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
    keys: tuple[KeyType, ...],
    values: tuple[ValueType, ...],
) -> "ImmutableDict[KeyType,ValueType]":
    """Restore ImmutableDict from its pickled keys and values.

    The tuples are stored as they are: a stream that does not come from `__reduce__` must not build a dictionary
    the constructor would refuse, so the shape is checked first.

    Args:
        keys: Keys of the dictionary.
        values: Values of the dictionary, in the order of the keys.

    Returns:
        New ImmutableDict instance with the provided data.

    Raises:
        ValueError: The arguments are not two tuples of the same length, or a key is repeated.

    post: __return__._keys == keys
    post: __return__._values == values
    raises: ValueError
    """
    if not (isinstance(keys, tuple) and isinstance(values, tuple)) or len(keys) != len(values):
        raise ValueError("Invalid ImmutableDict state: keys and values must be two tuples of the same length")
    if len(set(keys)) != len(keys):
        raise ValueError("Invalid ImmutableDict state: a key is repeated")
    return cast("ImmutableDict[KeyType, ValueType]", tuple.__new__(ImmutableDict, (keys, values)))


class ImmutableDict(
    tuple[tuple[KeyType, ...], tuple[ValueType, ...]],
    collections.abc.Mapping,
    Generic[KeyType, ValueType],
):
    """
    An immutable dictionary-like object built on a tuple of tuples.
    This class is compatible with the collections.abc.Mapping kind.
    """

    __slots__ = ()

    # construction accepts either a Mapping or an iterable of (key, value) pairs
    def __new__(
        cls,
        data: Mapping[KeyType, ValueType] | Iterable[tuple[KeyType, ValueType]],
    ) -> "ImmutableDict[KeyType, ValueType]":
        """Create new ImmutableDict instance.

        Args:
            data: Either a mapping or iterable of (key, value) pairs.

        Returns:
            New ImmutableDict instance.
        """
        # Normalize incoming data to an iterable of pairs
        keys: tuple[KeyType, ...]
        values: tuple[ValueType, ...]
        if isinstance(data, ImmutableDict):
            keys = data._keys
            values = data._values
        else:
            if isinstance(data, Mapping):
                keys = cast(tuple[KeyType, ...], tuple(data.keys()))
                values = cast(tuple[ValueType, ...], tuple(data.values()))
            else:
                # allow any iterable of (k, v) pairs
                pairs = dict(data)
                keys = tuple(pairs.keys())
                values = tuple(pairs.values())

        # Create the tuple-subclass with two items: (keys, values)
        obj = tuple.__new__(cls, (keys, values))
        return obj

    def __deepcopy__(self, memo: dict[int, Any]) -> "ImmutableDict[KeyType, ValueType]":
        """Copy the keys and the values, which already satisfy what `_restore_pickle` checks of a stream.

        Args:
            memo: The memo of `copy.deepcopy`.

        Returns:
            New ImmutableDict instance holding copies of the keys and the values.
        """
        keys = copy.deepcopy(self._keys, memo)
        values = copy.deepcopy(self._values, memo)
        return cast("ImmutableDict[KeyType, ValueType]", tuple.__new__(ImmutableDict, (keys, values)))

    def __reduce__(self) -> tuple[Callable[..., Any], tuple[Any, ...]]:
        """Support for pickle serialization.

        Returns:
            Tuple for pickle reconstruction.
        """
        return (_restore_pickle, (self._keys, self._values))

    @property
    def _keys(self) -> tuple[KeyType, ...]:
        """Get tuple of all keys.

        Returns:
            Tuple containing all dictionary keys.
        """
        return tuple.__getitem__(self, 0)  # type: ignore[index]

    @property
    def _values(self) -> tuple[ValueType, ...]:
        """Get tuple of all values.

        Returns:
            Tuple containing all dictionary values.
        """
        return tuple.__getitem__(self, 1)  # type: ignore[index]

    # Mapping kind
    def __getitem__(self, key: KeyType) -> ValueType:  # type: ignore[override]
        """Get value by key.

        Args:
            key: Key to look up.

        Returns:
            Value associated with the key.

        Raises:
            KeyError: If key is not found.

        pre: key in self._keys
        post: __return__ is self._values[self._keys.index(key)]
        """
        try:
            idx = self._keys.index(key)
        except ValueError as e:
            raise KeyError(key) from e
        return cast(ValueType, self._values[idx])

    def __iter__(self) -> Iterator[KeyType]:  # type: ignore[override]
        """Iterate over keys.

        Returns:
            Iterator over dictionary keys.
        """
        return iter(self._keys)

    def __len__(self) -> int:
        """Get number of key-value pairs.

        Returns:
            Number of items in the dictionary.

        post: __return__ >= 0
        post: __return__ == len(self._values)
        """
        return len(self._keys)

    def __contains__(self, key: object) -> bool:
        """Check if key exists in dictionary.

        Args:
            key: Key to check for existence.

        Returns:
            True if key exists, False otherwise.

        post: __return__ == (key in self._keys)
        """
        try:
            self._keys.index(key)  # type: ignore[arg-type]
            return True
        except ValueError:
            return False

    def __eq__(self, other: object) -> bool:
        """Compare as a mapping, whatever the insertion order, plain dicts included."""
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        # Not NotImplemented: Python would then fall back on tuple equality with the storage tuple.
        return False

    def __ne__(self, other: object) -> bool:
        """Negate `__eq__`, which tuple's own `__ne__` would bypass."""
        return not self.__eq__(other)

    def __hash__(self) -> int:
        """Hash consistently with `__eq__`, whatever the insertion order."""
        return hash(frozenset(self.items()))

    def __repr__(self) -> str:
        """String representation of the dictionary.

        Returns:
            String representation in ImmutableDict format.
        """
        return f"ImmutableDict({dict(zip(self._keys, self._values,strict=True))})"

    # Keep Mapping's default .keys(), .items(), .values()
    def keys(self) -> KeysView[KeyType]:
        """Get view of dictionary keys.

        Returns:
            Keys view of the dictionary.
        """
        return Mapping.keys(self)

    def items(self) -> ItemsView[KeyType, ValueType]:
        """Get view of dictionary items.

        Returns:
            Items view of the dictionary.
        """
        return Mapping.items(self)

    def values(self) -> ValuesView[ValueType]:
        """Get view of dictionary values.

        Returns:
            Values view of the dictionary.
        """
        return Mapping.values(self)
