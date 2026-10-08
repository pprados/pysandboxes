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


def test_unenv_removes_a_key_declared_after_it() -> None:
    """`unenv` wins over `env`, whatever the order of the rules."""
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
    assert env == Envs({})


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


def _set_on_the_host(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    """Set a variable as the host's, present before learning: the code did not write it."""
    monkeypatch.setitem(os.environ, key, value)
    LearnEnviron()._written.discard(key)


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

    # The code's own writes need no rule: only the read is learned.
    assert learning_environ == {"READ_VAR"}
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


def test_bytes_names_are_passed_unchanged_by_putenv_and_unsetenv(learning_environ: Set[str]) -> None:
    """Bytes names reach the OS wrappers unchanged, and a write learns nothing."""
    calls: List[Tuple[str, Any]] = []
    table: dict[str, Callable[..., Any]] = patch_rules(learn=True)
    putenv = table["os.putenv"](lambda name, value: calls.append(("putenv", (name, value))))
    unsetenv = table["os.unsetenv"](lambda name: calls.append(("unsetenv", name)))

    putenv(b"BYTES_SET", b"value")
    unsetenv(b"BYTES_REMOVED")

    assert not learning_environ
    assert calls == [
        ("putenv", (b"BYTES_SET", b"value")),
        ("unsetenv", b"BYTES_REMOVED"),
    ]


def test_reading_a_variable_records_it(learning_environ: Set[str]) -> None:
    os.environ["PATH"]

    assert "PATH" in learning_environ


def test_writing_a_variable_learns_nothing(learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The sandbox lets the code set any variable: a rule would only bring in the host's value."""
    monkeypatch.setitem(os.environ, "WRITTEN", "value")

    assert "WRITTEN" not in learning_environ


def test_reading_back_a_variable_the_code_set_learns_nothing(
    learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """What load_dotenv() does: set each name of the .env, then the code reads it."""
    monkeypatch.setitem(os.environ, "FROM_DOTENV", "value")
    del os.environ["FROM_DOTENV"]
    monkeypatch.setitem(os.environ, "FROM_DOTENV", "value")

    assert os.environ["FROM_DOTENV"] == "value"
    assert os.getenv("FROM_DOTENV") == "value"
    assert "FROM_DOTENV" in os.environ
    assert "FROM_DOTENV" not in learning_environ


def test_a_read_before_the_code_writes_the_variable_is_learned(
    learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_on_the_host(monkeypatch, "SET_AFTER_READ", "host")
    assert os.environ["SET_AFTER_READ"] == "host"
    monkeypatch.setitem(os.environ, "SET_AFTER_READ", "code")

    assert "SET_AFTER_READ" in learning_environ


def test_learning_environ_updates_are_visible_through_environb(monkeypatch: pytest.MonkeyPatch) -> None:
    environb = getattr(os, "environb", None)
    if environb is None:
        pytest.skip("os.environb is unavailable on this platform")

    monkeypatch.setitem(os.environ, "LEARNED_BYTES_VIEW", "value")

    assert environb[b"LEARNED_BYTES_VIEW"] == b"value"


def test_environb_writes_learn_nothing_through_putenv(
    learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    environb = getattr(os, "environb", None)
    if environb is None:
        pytest.skip("os.environb is unavailable on this platform")

    putenv = patch_rules(learn=True)["os.putenv"](os.putenv)
    monkeypatch.setattr(os, "putenv", putenv)
    monkeypatch.setitem(environb, b"LEARNED_ENVIRONB_WRITE", b"value")

    assert "LEARNED_ENVIRONB_WRITE" not in learning_environ


def test_environb_reads_are_learned(learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(os, "environb"):
        pytest.skip("os.environb is unavailable on this platform")

    environb = patch_rules(learn=True)["os.environb"](None)
    monkeypatch.setattr(os, "environb", environb)
    _set_on_the_host(monkeypatch, "LEARNED_ENVIRONB_READ", "value")

    assert os.environb[b"LEARNED_ENVIRONB_READ"] == b"value"
    assert "LEARNED_ENVIRONB_READ" in learning_environ


def test_getenvb_reads_are_learned(learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(os, "getenvb"):
        pytest.skip("os.getenvb is unavailable on this platform")

    environb = patch_rules(learn=True)["os.environb"](None)
    monkeypatch.setattr(os, "environb", environb)
    getenvb = patch_rules(learn=True)["os.getenvb"](os.getenvb)
    monkeypatch.setattr(os, "getenvb", getenvb)
    _set_on_the_host(monkeypatch, "LEARNED_GETENVB_READ", "value")

    assert os.getenvb(b"LEARNED_GETENVB_READ") == b"value"
    assert "LEARNED_GETENVB_READ" in learning_environ


def test_getenvb_learns_missing_keys_and_preserves_default(
    learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, "getenvb"):
        pytest.skip("os.getenvb is unavailable on this platform")

    environb = patch_rules(learn=True)["os.environb"](None)
    monkeypatch.setattr(os, "environb", environb)
    getenvb = patch_rules(learn=True)["os.getenvb"](os.getenvb)
    monkeypatch.setattr(os, "getenvb", getenvb)

    assert os.getenvb(b"LEARNED_GETENVB_MISSING", b"fallback") == b"fallback"
    assert "LEARNED_GETENVB_MISSING" in learning_environ


def test_environb_learns_keys_using_filesystem_surrogateescape(
    learning_environ: Set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, "environb"):
        pytest.skip("os.environb is unavailable on this platform")

    key = b"LEARNED_ENVIRONB_\xff"
    environb = patch_rules(learn=True)["os.environb"](None)
    monkeypatch.setattr(os, "environb", environb)
    _set_on_the_host(monkeypatch, os.fsdecode(key), "value")

    assert os.environb[key] == b"value"
    assert os.fsdecode(key) in learning_environ


def test_copying_the_environment_does_not_learn_every_key(learning_environ: Set[str]) -> None:
    expected = LearnEnviron()._clone()

    assert dict(os.environ) == expected
    assert learning_environ <= {"PYTEST_CURRENT_TEST"}


def test_reading_a_key_after_scanning_records_the_access(learning_environ: Set[str]) -> None:
    keys = list(os.environ)
    assert keys
    key = keys[0]

    os.environ[key]

    assert f"env={key}=${{{key}}}" in generate_rules()


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
    expected = {
        "os.environ",
        "os.getenv",
        "os.putenv",
        "os.unsetenv",
    }
    if hasattr(os, "environb"):
        expected.update({"os.environb", "os.getenvb"})
    assert set(patch_rules(learn=True)) == expected


# TODO: test activate with os.environ and os.environb


def test_disarming_clears_the_rules_a_learning_run_would_read() -> None:
    """``generate_rules()`` skips any variable an armed rule already covers.

    Rules left over from an earlier arming therefore make a later learning run
    under-report what it saw, which is a silently incomplete profile.
    """
    from pysandboxes.guard_envs import _deactivate_guard_envs

    errors: List[ErrorMsg] = []
    rules, _, _ = parse_rules([ConfigLine("env=MY_VAR=1", Path(), 0)], {"MY_VAR": "1"}, errors)
    assert not errors
    activate_guard(rules)

    LearnEnviron()._keys_used.add("MY_VAR")
    assert "env=MY_VAR=${MY_VAR}" not in generate_rules(), "an armed rule must hide the variable"

    _deactivate_guard_envs()

    assert "env=MY_VAR=${MY_VAR}" in generate_rules(), "a disarmed guard must hide nothing"
