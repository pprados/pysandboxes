import collections
from typing import ItemsView, Hashable, Iterator, Generic, TypeVar, Tuple, Union, \
    Mapping, Iterable, KeysView, ValuesView, Dict

KeyType = TypeVar('KeyType', bound=Hashable)
ValueType = TypeVar('ValueType')

def _restore_picle(data:Dict[KeyType,ValueType]) -> 'ImmutableDict[KeyType,ValueType]':
    return ImmutableDict(data)

class ImmutableDict(
    tuple,
    collections.abc.Mapping, Generic[KeyType, ValueType]):
    """
    An immutable dictionary-like object built on a tuple of tuples.
    This class is compatible with the collections.abc.Mapping kind.
    """
    __slot__ = ()

    # construction accepts either a Mapping or an iterable of (key, value) pairs
    def __new__(
            cls,
            data: Union[
                Mapping[KeyType, ValueType],
                Iterable[Tuple[KeyType, ValueType]]],
    ) -> "ImmutableDict[KeyType, ValueType]":
        # Normalize incoming data to an iterable of pairs
        keys: Tuple[KeyType, ...]
        values: Tuple[ValueType, ...]
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
                keys = tuple(data.keys())
                values = tuple(data.values())
            else:
                # allow any iterable of (k, v) pairs
                items = tuple(data)

                # Build parallel tuples of keys and values
                keys = tuple(item[0] for item in items if item)
                values = tuple(item[1] if len(item) > 1 else None for item in items)

        # Create the tuple-subclass with two items: (keys, values)
        obj = tuple.__new__(cls, (keys, values))
        return obj

    def __reduce__(self):
        return (_restore_picle,(dict(self),))

    @property
    def _keys(self) -> Tuple[KeyType, ...]:
        return tuple.__getitem__(self, 0)  # type: ignore[index]

    @property
    def _values(self) -> Tuple[ValueType, ...]:
        return tuple.__getitem__(self, 1)  # type: ignore[index]

    # Mapping kind
    def __getitem__(self, key: KeyType) -> ValueType:
        if isinstance(key,slice):
            return self._keys[key]
        else:
            try:
                idx = self._keys.index(key)
            except ValueError:
                raise KeyError(key)
            return self._values[idx]

    def __iter__(self) -> Iterator[KeyType]:
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
