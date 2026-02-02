import collections
from typing import ItemsView, Hashable, Any, Iterator, Generic, TypeVar, Tuple

KeyType = TypeVar('KeyType', bound=Hashable)
ValueType = TypeVar('ValueType')
class ImmutableDict(collections.abc.Mapping,Generic[KeyType, ValueType]):
    """
    An immutable dictionary-like object built on a tuple of tuples.
    This class is compatible with the collections.abc.Mapping protocol.
    """
    __slot__ = ('_kv')
    _key: Tuple[Hashable, ...]
    _value: Tuple[Any, ...]

    def __init__(self, data: collections.abc.Mapping[Hashable, Any]):
        """
        Initializes the ImmutableDict from an iterable of key-value pairs.

        Args:
            data: An iterable of (key, value) tuples.
        """
        data = tuple(list(data.items()))
        self._kv = (
            tuple(item[0] for item in data),
            tuple(item[1] for item in data)
        )

    def __getitem__(self, key: Hashable) -> Any:
        """
        Retrieves the value for a given key.

        Args:
            key: The key to look for.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If the key is not found.
        """
        try:
            index = self._kv[0].index(key)
            return self._kv[1][index]
        except ValueError:
            raise KeyError(f"Key not found: {key}")

    def __len__(self) -> int:
        """
        Returns the number of key-value pairs in the dictionary.
        """
        return len(self._kv[0])

    def __iter__(self) -> Iterator[Hashable]:
        """
        Returns an iterator over the keys.
        """
        return iter(self._kv[0])

    def __repr__(self) -> str:
        """
        Returns a string representation of the object.
        """
        return f"ImmutableDict({dict(zip(*self._kv))})"

    # Optional method to provide a view of the items, similar to a standard dict
    def items(self) -> ItemsView[Hashable, Any]:
        """
        Returns a view object that displays a list of a given dictionary’s
        (key, value) tuple pairs.
        """
        return dict(zip(*self._kv)).items()
