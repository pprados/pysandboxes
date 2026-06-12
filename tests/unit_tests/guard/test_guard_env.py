from pathlib import Path
from typing import List, Set

import pytest

from pysandboxes import guard_envs
from pysandboxes.guard_envs import (
    LearnEnviron,
    activate_guard,
    generate_rules,
    parse_rules,
    patch_rules,
)
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, Envs


def test_simple_env() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=FOO=bar", Path(), 0),
        ],
        {},
        errors,
    )

    assert env == Envs({"FOO": "bar"})


def test_var_value() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=FOO=${bar}", Path(), 0),
        ],
        {"bar": "BAR"},
        errors,
    )
    assert env == Envs({"FOO": "BAR"})


def test_var_default_value() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=FOO=${X:-BAR}", Path(), 0),
        ],
        {"bar": "BAR"},
        errors,
    )
    assert env == Envs({"FOO": "BAR"})


def test_var_pattern() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0),
        ],
        {"APP1_API_KEY": "123", "APP2_API_KEY": "456"},
        errors,
    )
    assert env == Envs({"APP1_API_KEY": "123", "APP2_API_KEY": "456"})


def test_var_all_pattern() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=*=${*}", Path(), 0),
        ],
        {"APP1_API_KEY": "123", "APP2_API_KEY": "456"},
        errors,
    )
    assert env == Envs({"APP1_API_KEY": "123", "APP2_API_KEY": "456"})


def test_var_all_pattern_and_unset() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("env=*=${*}", Path(), 0),
            ConfigLine("unenv=APP1_API_KEY", Path(), 0),
        ],
        {"APP1_API_KEY": "123", "APP2_API_KEY": "456"},
        errors,
    )
    assert env == Envs({"APP2_API_KEY": "456"})


def test_missing_equal_is_reported() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules([ConfigLine("env=FOO", Path("cfg"), 3)], {}, errors)

    assert len(errors) == 1
    assert "missing '='" in errors[0][0]
    assert errors[0][1] == Path("cfg")
    assert errors[0][2] == 3
    assert env == Envs({})


def test_other_directives_are_returned_untouched() -> None:
    errors: List[ErrorMsg] = []
    _, env, ignored = parse_rules(
        [
            ConfigLine("env=FOO=bar", Path(), 0),
            ConfigLine("python-import=os", Path(), 0),
        ],
        {},
        errors,
    )

    assert not errors
    assert env == Envs({"FOO": "bar"})
    assert [line.rule for line in ignored] == ["python-import=os"]


def test_unknown_variable_leaves_the_key_absent() -> None:
    """An unset `${...}` source keeps the key out, so `os.getenv(key, default)` returns the default."""
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules([ConfigLine("env=FOO=${MISSING}", Path(), 0)], {}, errors)

    assert not errors
    assert env == Envs({})


def test_wildcard_skips_empty_source_values() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0)],
        {"APP1_API_KEY": "123", "APP2_API_KEY": ""},
        errors,
    )

    assert not errors
    assert env == Envs({"APP1_API_KEY": "123"})


def test_unenv_only_removes_what_is_already_declared() -> None:
    """`unenv` acts on the environment built so far, so the order of the rules matters."""
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules(
        [
            ConfigLine("unenv=FOO", Path(), 0),
            ConfigLine("env=FOO=bar", Path(), 0),
        ],
        {},
        errors,
    )

    assert not errors
    assert env == Envs({"FOO": "bar"})


def test_unenv_of_an_unknown_key_is_not_an_error() -> None:
    errors: List[ErrorMsg] = []
    _, env, _ = parse_rules([ConfigLine("unenv=NEVER_SET", Path(), 0)], {}, errors)

    assert not errors
    assert env == Envs({})


def test_rules_flag_env_and_unenv() -> None:
    errors: List[ErrorMsg] = []
    rules, _, _ = parse_rules(
        [
            ConfigLine("env=FOO=bar", Path(), 0),
            ConfigLine("unenv=BAZ", Path(), 0),
        ],
        {},
        errors,
    )

    assert not errors
    by_ignore = {rule.ignore: rule for rule in rules}
    assert by_ignore[False].pattern.match("FOO")
    assert by_ignore[True].pattern.match("BAZ")


def test_wildcard_rule_keeps_a_matching_pattern() -> None:
    errors: List[ErrorMsg] = []
    rules, _, _ = parse_rules([ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0)], {}, errors)

    assert not errors
    assert len(rules) == 1
    assert rules[0].pattern.match("ANY_API_KEY")
    assert not rules[0].pattern.match("OTHER")


@pytest.fixture
def learned_keys(monkeypatch: pytest.MonkeyPatch) -> Set[str]:
    """Give a fresh singleton and a clean set of observed keys, restored afterwards."""
    monkeypatch.setattr(guard_envs, "_rules", ())
    monkeypatch.setattr(LearnEnviron, "_instance", None)
    return LearnEnviron()._keys_used


def test_learn_environ_is_a_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LearnEnviron, "_instance", None)
    assert LearnEnviron() is LearnEnviron()


def test_generate_rules_emits_one_line_per_observed_key(learned_keys: Set[str]) -> None:
    activate_guard(())
    learned_keys.update({"B_VAR", "A_VAR"})

    assert generate_rules() == ["env=A_VAR=${A_VAR}", "env=B_VAR=${B_VAR}"]


def test_generate_rules_skips_keys_already_covered_by_a_rule(learned_keys: Set[str]) -> None:
    errors: List[ErrorMsg] = []
    rules, _, _ = parse_rules([ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0)], {}, errors)
    activate_guard(rules)
    learned_keys.update({"APP_API_KEY", "OTHER"})

    assert generate_rules() == ["env=OTHER=${OTHER}"]


def test_no_patch_without_learning() -> None:
    assert patch_rules(learn=False) == {}


def test_patch_covers_the_environment_entry_points() -> None:
    assert set(patch_rules(learn=True)) == {
        "os.environ",
        "os.getenv",
        "os.putenv",
        "os.unsetenv",
    }


# TODO: test activate with os.environ and os.environb
