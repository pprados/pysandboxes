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
    """Restore ImmutableDict from pickled data.

    Args:
        data: Dictionary data to restore from.

    Returns:
        New ImmutableDict instance with the provided data.
    """
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
        """Support for pickle serialization.

        Returns:
            Tuple for pickle reconstruction.
        """
        return (_restore_pickle, (dict(self),))

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
        """
        try:
            idx = self._keys.index(key)
        except ValueError:
            raise KeyError(key)
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
        """
        return len(self._keys)

    def __contains__(self, key: object) -> bool:
        """Check if key exists in dictionary.

        Args:
            key: Key to check for existence.

        Returns:
            True if key exists, False otherwise.
        """
        try:
            self._keys.index(key)  # type: ignore[arg-type]
            return True
        except ValueError:
            return False

    def __repr__(self) -> str:
        """String representation of the dictionary.

        Returns:
            String representation in ImmutableDict format.
        """
        return f"ImmutableDict({dict(zip(self._keys, self._values))})"

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
