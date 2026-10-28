# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import pickle

import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes.immutable_dict import ImmutableDict

keys = st.one_of(st.integers(), st.text(max_size=5))
mappings = st.dictionaries(keys, st.integers(), max_size=8)


@given(mappings)
def test_new_from_mapping_keeps_every_pair(data: dict[object, int]) -> None:
    frozen = ImmutableDict(data)
    assert dict(frozen) == data
    assert len(frozen) == len(data)
    assert list(frozen) == list(data)


@given(st.lists(st.tuples(keys, st.integers()), max_size=8))
def test_new_from_pairs_last_duplicate_wins(pairs: list[tuple[object, int]]) -> None:
    assert dict(ImmutableDict(pairs)) == dict(pairs)


@given(mappings)
def test_new_from_immutable_dict_is_equal(data: dict[object, int]) -> None:
    frozen = ImmutableDict(data)
    assert ImmutableDict(frozen) == frozen


@pytest.mark.parametrize("bad", [None, 3, [1], [(1, 2, 3)]])
def test_new_rejects_non_mapping_input(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ImmutableDict(bad)  # type: ignore[arg-type]


@given(mappings)
def test_getitem_and_contains_agree_with_dict(data: dict[object, int]) -> None:
    frozen = ImmutableDict(data)
    for key, value in data.items():
        assert key in frozen
        assert frozen[key] == value


@given(mappings, keys)
def test_missing_key_raises_key_error(data: dict[object, int], key: object) -> None:
    frozen = ImmutableDict(data)
    if key in data:
        assert frozen[key] == data[key]
    else:
        assert key not in frozen
        with pytest.raises(KeyError):
            frozen[key]


@given(mappings)
def test_hash_ignores_insertion_order(data: dict[object, int]) -> None:
    reordered = dict(reversed(list(data.items())))
    assert ImmutableDict(data) == ImmutableDict(reordered)
    assert hash(ImmutableDict(data)) == hash(ImmutableDict(reordered))


def test_hash_of_unhashable_value_raises_type_error() -> None:
    with pytest.raises(TypeError):
        hash(ImmutableDict({"a": [1]}))


@given(mappings)
def test_equality_with_plain_dict_and_ne(data: dict[object, int]) -> None:
    frozen = ImmutableDict(data)
    assert frozen == data
    assert not frozen != data
    assert frozen != {**data, object(): 0}


@pytest.mark.parametrize("other", [(), ((), ()), [], "x", None])
def test_not_equal_to_non_mapping(other: object) -> None:
    assert ImmutableDict({}) != other
    assert not ImmutableDict({}) == other


@given(mappings)
def test_pickle_roundtrip(data: dict[object, int]) -> None:
    frozen = ImmutableDict(data)
    restored = pickle.loads(pickle.dumps(frozen))
    assert restored == frozen
    assert isinstance(restored, ImmutableDict)


def test_repr_names_the_class_and_shows_the_content() -> None:
    assert repr(ImmutableDict({"a": 1})) == "ImmutableDict({'a': 1})"


def test_no_mutation_entry_point() -> None:
    frozen = ImmutableDict({"a": 1})
    for name in ("__setitem__", "__delitem__", "update", "pop", "clear", "setdefault"):
        assert not hasattr(frozen, name)
    with pytest.raises(TypeError):
        frozen["a"] = 2  # type: ignore[index]
    with pytest.raises(AttributeError):
        frozen.x = 1  # type: ignore[attr-defined]
