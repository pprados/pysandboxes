import pytest

from pysandboxes.immutable_dict import ImmutableDict


def test_immutable_dict():
    # Création d'une instance à partir d'un dictionnaire
    original_dict = {"a": 1, "b": 2, "c": 3}
    my_immutable_dict = ImmutableDict(original_dict)

    # Access a value
    assert my_immutable_dict['b'] == original_dict['b']

    # Access list of keys
    assert list(original_dict) == list(my_immutable_dict)

    # Access list of values
    assert list(original_dict.values()) == list(my_immutable_dict.values())

    # Check key
    assert "a" in my_immutable_dict

    # Check immutability
    with pytest.raises(TypeError):
        my_immutable_dict["a"] = 10

def test_empty_immutable_dict():
    my_immutable_dict = ImmutableDict({})
    my_immutable_dict.keys()
    my_immutable_dict.values()
    import pickle
    p=pickle.dumps(my_immutable_dict)
    pickle.loads(p)