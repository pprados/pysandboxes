import copy
import pickle

import pytest  # type: ignore[import-untyped]

from pysandboxes.immutable_dict import ImmutableDict, _restore_pickle


def test_immutable_dict() -> None:
    # Création d'une instance à partir d'un dictionnaire
    original_dict = {"a": 1, "b": 2, "c": 3}
    my_immutable_dict = ImmutableDict(original_dict)

    # Access a value
    assert my_immutable_dict["b"] == original_dict["b"]

    # Access list of keys
    assert list(original_dict) == list(my_immutable_dict)

    # Access list of values
    assert list(original_dict.values()) == list(my_immutable_dict.values())

    # Check key
    assert "a" in my_immutable_dict

    # Check immutability
    with pytest.raises(TypeError):
        my_immutable_dict["a"] = 10  # type: ignore[index]


@pytest.mark.parametrize(
    "keys, values",
    [
        (("a", "a"), (1, 2)),
        (("a", "b"), (1,)),
        (["a"], (1,)),
        (("a",), [1]),
    ],
)
def test_a_forged_state_is_refused(keys: object, values: object) -> None:
    with pytest.raises(ValueError, match="Invalid ImmutableDict state"):
        _restore_pickle(keys, values)  # type: ignore[arg-type]


def test_pickle_and_deepcopy_keep_order_and_values() -> None:
    original = ImmutableDict({"b": [1], "a": 2})
    for clone in (pickle.loads(pickle.dumps(original)), copy.deepcopy(original)):
        assert isinstance(clone, ImmutableDict)
        assert list(clone.items()) == list(original.items())
        assert clone == original
    assert copy.deepcopy(original)["b"] is not original["b"]
