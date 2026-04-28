import pickle
import pytest

from pysandboxes.guard_pickle import (
    PickleImportBlocker,
    safe_unpickle,
    parse_rules,
)


class SimpleDataClass:
    """Test data class for pickling."""

    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, SimpleDataClass) and self.value == other.value


def test_parse_rules_empty():
    """Test parsing empty configuration."""
    rules, remaining = parse_rules([])
    assert rules.allowed_classes == ()
    assert remaining == []


def test_parse_rules_single_class():
    """Test parsing single class whitelist rule."""
    rules, remaining = parse_rules(
        ["pickle-class=SimpleDataClass"],
    )
    assert rules.allowed_classes == ("SimpleDataClass",)
    assert remaining == []


def test_parse_rules_multiple_classes():
    """Test parsing multiple classes in whitelist."""
    rules, remaining = parse_rules(
        ["pickle-class=ClassA,ClassB,ClassC"],
    )
    assert rules.allowed_classes == ("ClassA", "ClassB", "ClassC")
    assert remaining == []


def test_parse_rules_wildcard():
    """Test parsing wildcard (allow all) - for testing only."""
    rules, remaining = parse_rules(
        ["pickle-class=*"],
    )
    assert rules.allowed_classes == ("*",)
    assert remaining == []


def test_parse_rules_mixed():
    """Test parsing mixed rules."""
    rules, remaining = parse_rules(
        ["pickle-class=ClassA,ClassB", "other-rule=value"],
    )
    assert rules.allowed_classes == ("ClassA", "ClassB")
    assert remaining == ["other-rule=value"]


def test_safe_unpickle_builtin_types():
    """Test unpickling safe builtin types."""
    data_dict = {"key": "value", "count": 42}
    pickled = pickle.dumps(data_dict)

    result = safe_unpickle(pickled, allowed_classes=["dict", "str", "int"])
    assert result == data_dict


def test_safe_unpickle_list():
    """Test unpickling list (safe builtin)."""
    data_list = [1, 2, 3, "test"]
    pickled = pickle.dumps(data_list)

    result = safe_unpickle(pickled, allowed_classes=["list", "int", "str"])
    assert result == data_list


def test_safe_unpickle_rejected_class():
    """Test that non-whitelisted classes are rejected."""
    data = SimpleDataClass("test")
    pickled = pickle.dumps(data)

    with pytest.raises(pickle.UnpicklingError) as exc_info:
        safe_unpickle(pickled, allowed_classes=["dict", "str"])

    assert "not in whitelist" in str(exc_info.value)


def test_safe_unpickle_dangerous_builtin():
    """Test that custom classes are restricted without whitelist."""
    # Pickle a custom class - this will require find_class
    obj = SimpleDataClass("test")
    pickled = pickle.dumps(obj)

    # Without SimpleDataClass whitelisted, should be rejected
    with pytest.raises(pickle.UnpicklingError) as exc_info:
        safe_unpickle(pickled, allowed_classes=["list", "str"])

    assert "not in whitelist" in str(exc_info.value)


def test_safe_unpickle_wildcard_allows_all():
    """Test wildcard allows all classes (for testing)."""
    data = SimpleDataClass("test")
    pickled = pickle.dumps(data)

    # With wildcard, should accept anything
    result = safe_unpickle(pickled, allowed_classes=["*"])
    assert result == data


def test_safe_unpickle_empty_allowlist():
    """Test unpickling with empty allowlist blocks custom classes."""
    # Custom class needs to be in whitelist
    obj = SimpleDataClass("test")
    pickled = pickle.dumps(obj)

    with pytest.raises(pickle.UnpicklingError) as exc_info:
        # SimpleDataClass not in allowed list
        safe_unpickle(pickled, allowed_classes=[])

    assert "not in whitelist" in str(exc_info.value)


def test_safe_unpickle_tuple_allowed_classes():
    """Test that tuple of allowed classes works."""
    data_list = [1, 2, 3]
    pickled = pickle.dumps(data_list)

    result = safe_unpickle(pickled, allowed_classes=("list", "int"))
    assert result == data_list


def test_pickle_import_blocker_find_spec():
    """Test that PickleImportBlocker exists and has find_spec method."""
    blocker = PickleImportBlocker()
    assert hasattr(blocker, "find_spec")
    assert callable(blocker.find_spec)


def test_safe_unpickle_none_allowed_classes():
    """Test safe_unpickle with None as allowed_classes blocks custom classes."""
    # Custom class needs to be in whitelist
    obj = SimpleDataClass("test")
    pickled = pickle.dumps(obj)

    with pytest.raises(pickle.UnpicklingError) as exc_info:
        # None means empty tuple - no custom classes allowed
        safe_unpickle(pickled, allowed_classes=None)

    assert "not in whitelist" in str(exc_info.value)


def test_safe_unpickle_nested_dict():
    """Test unpickling nested data structures."""
    data = {
        "outer": {
            "inner": [1, 2, 3],
            "value": "test",
        }
    }
    pickled = pickle.dumps(data)

    result = safe_unpickle(pickled, allowed_classes=["dict", "list", "int", "str"])
    assert result == data


def test_safe_unpickle_tuple():
    """Test unpickling tuple."""
    data = ("a", "b", "c")
    pickled = pickle.dumps(data)

    result = safe_unpickle(pickled, allowed_classes=["tuple", "str"])
    assert result == data


def test_safe_unpickle_set():
    """Test unpickling set."""
    data = frozenset([1, 2, 3])
    pickled = pickle.dumps(data)

    result = safe_unpickle(pickled, allowed_classes=["frozenset", "int"])
    assert result == data
