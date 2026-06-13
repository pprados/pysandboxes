import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable, List, Set, Tuple

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
    assert not by_ignore[False].pattern.match("FOOBAR")
    assert not by_ignore[True].pattern.match("BAZOOKA")


def test_wildcard_rule_keeps_a_matching_pattern() -> None:
    errors: List[ErrorMsg] = []
    rules, _, _ = parse_rules([ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0)], {}, errors)

    assert not errors
    assert len(rules) == 1
    assert rules[0].pattern.match("ANY_API_KEY")
    assert not rules[0].pattern.match("OTHER")
    assert not rules[0].pattern.match("ANY_API_KEYZZZ")


def test_wildcard_rule_does_not_forward_a_longer_key() -> None:
    """``*_API_KEY`` must match the suffix, not merely contain it."""
    errors: List[ErrorMsg] = []
    source = {"ANY_API_KEY": "kept", "ANY_API_KEY_AND_MORE": "leaked"}
    rules, envs, _ = parse_rules([ConfigLine("env=*_API_KEY=${*_API_KEY}", Path(), 0)], source, errors)

    assert not errors
    assert envs["ANY_API_KEY"] == "kept"
    assert "ANY_API_KEY_AND_MORE" not in envs


@pytest.fixture
def learned_keys(monkeypatch: pytest.MonkeyPatch) -> Set[str]:
    """Give a fresh singleton and a clean set of observed keys, restored afterwards."""
    monkeypatch.setattr(guard_envs, "_rules", ())
    monkeypatch.setattr(LearnEnviron, "_instance", None)
    return LearnEnviron()._keys_used


@pytest.fixture
def learning_environ(learned_keys: Set[str], monkeypatch: pytest.MonkeyPatch) -> Set[str]:
    """Install the learning environment the wrappers assert on."""
    monkeypatch.setattr(os, "environ", LearnEnviron())
    return learned_keys


def test_the_environment_wrappers_record_the_key(learning_environ: Set[str]) -> None:
    """patch_rules had its dict keys compared, never its wrappers called.

    All three could have stopped recording, or stopped calling through, with
    the existing test still green.
    """
    calls: List[Tuple[str, Any]] = []
    table: dict[str, Callable[..., Any]] = patch_rules(learn=True)

    getenv = table["os.getenv"](lambda key, default=None: calls.append(("getenv", key)))
    putenv = table["os.putenv"](lambda name, value: calls.append(("putenv", name)))
    unsetenv = table["os.unsetenv"](lambda name: calls.append(("unsetenv", name)))

    getenv("READ_VAR")
    putenv("WRITTEN_VAR", "value")
    unsetenv("REMOVED_VAR")

    assert learning_environ >= {"READ_VAR", "WRITTEN_VAR", "REMOVED_VAR"}
    assert calls == [
        ("getenv", "READ_VAR"),
        ("putenv", "WRITTEN_VAR"),
        ("unsetenv", "REMOVED_VAR"),
    ]


def test_a_bytes_key_is_recorded_decoded(learning_environ: Set[str]) -> None:
    """The generated rule is a name, so a bytes key must not be stored raw."""
    getenv = patch_rules(learn=True)["os.getenv"](lambda key, default=None: None)

    getenv(b"BYTES_VAR")

    assert "BYTES_VAR" in learning_environ


def test_reading_a_variable_records_it(learning_environ: Set[str]) -> None:
    os.environ["PATH"]

    assert "PATH" in learning_environ


_ROOT = Path(__file__).resolve().parents[3]


def test_iterating_the_environment_yields_every_key_at_module_level() -> None:
    """Iteration must not depend on how deep the caller sits.

    Attributing a key to its reader walks two frames back. At module level
    there is no such frame, and the key was dropped instead of yielded, so a
    top-level ``for k in os.environ`` saw an empty environment while len()
    and dict() still reported every variable. Only a fresh process reproduces
    that depth: under pytest the stack is always deeper.
    """
    script = textwrap.dedent("""
        import os
        from pysandboxes.guard_envs import LearnEnviron

        expected = len(os.environ)
        os.environ = LearnEnviron()
        print(expected, len([k for k in os.environ]))
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_ROOT,
    )

    assert result.returncode == 0, result.stderr
    expected, seen = result.stdout.split()
    assert int(expected) > 0
    assert seen == expected


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
