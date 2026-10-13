# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_provider layer.

Complements ``tests/unit_tests/test_guard_provider.py``, which covers the nominal
values with mocked paths. Here the cases left uncovered are checked against a real
filesystem, so the `learn` resolution can be observed instead of simulated.
"""

from pathlib import Path
from typing import Any

import pytest

from pysandboxes.config import CONFIG_NAME
from pysandboxes.guard_provider import parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, ConfigLines

# Index of each field in the tuple returned by parse_rules().
PORT, PROVIDER, PY_SANDBOX, LEARNING_PATH, LEARN, RESULT_GUARD, RESULT_DATA_ONLY, OTHER = range(8)

# A rule whose path is Path(".") comes from the command line and wins over the files.
FROM_ARG = Path(".")


def _parse(
    *rules: str,
    config_path: Path,
    rule_path: Path = FROM_ARG,
) -> tuple[tuple[Any, ...], list[ErrorMsg]]:
    errors: list[ErrorMsg] = []
    lines: ConfigLines = [ConfigLine(rule, rule_path, i + 1) for i, rule in enumerate(rules)]
    return parse_rules(config_path, lines, errors), errors


@pytest.fixture
def existing_config(tmp_path: Path) -> Path:
    """A learning file that already exists, so the learn mode is not forced."""
    config = tmp_path / CONFIG_NAME
    config.write_text("")
    return config


@pytest.mark.parametrize("value", ["  FireJail  ", "BWRAP"])
def test_os_sandbox_is_case_and_space_insensitive(
    value: str, existing_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")  # A Linux backend, parsed on any host
    result, errors = _parse(f"os-sandbox={value}", config_path=existing_config)
    assert not errors
    assert result[PROVIDER] == value.strip().lower()


@pytest.mark.parametrize("value", ["", "true", "TRUE", "1"])
def test_py_sandbox_accepted_truthy_values(value: str, existing_config: Path) -> None:
    result, errors = _parse(f"py-sandbox={value}", config_path=existing_config)
    assert not errors
    assert result[PY_SANDBOX] is True


@pytest.mark.parametrize("value", ["FALSE", "none", "0"])
def test_py_sandbox_accepted_falsy_values(value: str, existing_config: Path) -> None:
    result, errors = _parse(f"py-sandbox={value}", config_path=existing_config)
    assert not errors
    assert result[PY_SANDBOX] is False


def test_an_empty_port_is_rejected(existing_config: Path) -> None:
    result, errors = _parse("port=", config_path=existing_config)
    assert len(errors) == 1
    assert "Port must be a positive value" in errors[0][0]
    assert result[PORT] == -1


@pytest.mark.parametrize("value", ["data-only", "DATA-ONLY"])
def test_remote_result_mode_accepts_data_only(value: str, existing_config: Path) -> None:
    result, errors = _parse(f"remote-result-mode={value}", config_path=existing_config)
    assert not errors
    assert result[RESULT_DATA_ONLY] is True


def test_remote_result_mode_defaults_to_data_only(existing_config: Path) -> None:
    result, errors = _parse(config_path=existing_config)
    assert not errors
    assert result[RESULT_DATA_ONLY] is True


@pytest.mark.parametrize("value", ["objects", "OBJECTS"])
def test_remote_result_mode_accepts_objects(value: str, existing_config: Path) -> None:
    result, errors = _parse(f"remote-result-mode={value}", config_path=existing_config)
    assert not errors
    assert result[RESULT_DATA_ONLY] is False


@pytest.mark.parametrize("value", ["false", "0", "1", "TRUE"])
def test_learn_refuses_a_boolean(value: str, existing_config: Path) -> None:
    """`learn` expects a filename; a boolean is a user mistake worth an error."""
    result, errors = _parse(f"learn={value}", config_path=existing_config)
    assert len(errors) == 1
    assert "Use the filename instead" in errors[0][0]
    assert result[PROVIDER] == "error"


def test_learn_without_value_falls_back_to_the_default_config_name(existing_config: Path) -> None:
    result, errors = _parse("learn=", config_path=existing_config)
    assert not errors
    assert result[LEARNING_PATH] == Path(CONFIG_NAME)
    assert result[LEARN] is True


def test_learn_keeps_an_explicit_directory(tmp_path: Path) -> None:
    target = tmp_path / "sub"
    target.mkdir()
    result, errors = _parse(f"learn={target / 'out.rules'}", config_path=tmp_path / CONFIG_NAME)
    assert not errors
    assert result[LEARNING_PATH] == target / "out.rules"


def test_learn_requires_an_existing_parent_directory(tmp_path: Path) -> None:
    result, errors = _parse(f"learn={tmp_path / 'missing' / 'out.rules'}", config_path=tmp_path / CONFIG_NAME)
    assert len(errors) == 1
    assert "The parent path must exist" in errors[0][0]


def test_disabling_the_py_sandbox_also_disables_an_explicit_learn_rule(tmp_path: Path) -> None:
    """Learning is implemented by the Python layer, so it cannot outlive it."""
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse("py-sandbox=false", "learn=my.rules", config_path=rule_file, rule_path=rule_file)
    assert not errors
    assert result[PY_SANDBOX] is False
    assert result[LEARN] is False


def test_the_same_value_twice_is_not_a_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rules are de-duplicated, so an include repeated twice stays valid."""
    monkeypatch.setattr("sys.platform", "linux")  # A Linux backend, parsed on any host
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    lines: ConfigLines = [ConfigLine("os-sandbox=firejail", rule_file, 1)] * 2
    errors: list[ErrorMsg] = []
    result = parse_rules(rule_file, lines, errors)
    assert not errors
    assert result[PROVIDER] == "firejail"


def test_errors_carry_their_provenance(tmp_path: Path) -> None:
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    _, errors = _parse("os-sandbox=nope", config_path=rule_file, rule_path=rule_file)
    assert errors[0][1] == rule_file
    assert errors[0][2] == 1


def test_learn_lock_ignores_a_rule_that_is_not_a_learn_directive(tmp_path: Path) -> None:
    """``learn_lock`` must match ``learn=`` rules specifically, not any file-sourced rule worth "false"."""
    missing_config = tmp_path / CONFIG_NAME
    result, errors = _parse("remote-result-guard=false", config_path=missing_config, rule_path=missing_config)
    assert not errors
    assert result[LEARN] is True


def test_learn_lock_does_not_duplicate_the_command_line_invalid_value_error(tmp_path: Path) -> None:
    """A command-line ``learn=false`` is already invalid: ``learn_lock`` must not also fire for it."""
    missing_config = tmp_path / CONFIG_NAME
    result, errors = _parse("learn=false", config_path=missing_config)  # rule_path defaults to the CLI
    assert len(errors) == 1
    assert "Invalid value 'false' for 'learn'" in errors[0][0]


def test_learn_lock_does_not_confuse_a_path_with_false(tmp_path: Path) -> None:
    """``learn_lock`` must match the literal value "false", not anything that sorts before it."""
    target = tmp_path / "audit.rules"
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse(f"learn={target}", config_path=rule_file, rule_path=rule_file)
    assert not errors
    assert result[LEARN] is True


@pytest.mark.parametrize("value", ["", "true", "1", "on"])
def test_remote_result_guard_accepts_truthy_values(value: str, existing_config: Path) -> None:
    result, errors = _parse(f"remote-result-guard={value}", config_path=existing_config)
    assert not errors
    assert result[RESULT_GUARD] is True


def test_remote_result_guard_defaults_to_true(existing_config: Path) -> None:
    result, errors = _parse(config_path=existing_config)
    assert not errors
    assert result[RESULT_GUARD] is True


def test_remote_result_mode_rejects_an_unrecognised_value_instead_of_defaulting_to_objects(
    existing_config: Path,
) -> None:
    result, errors = _parse("remote-result-mode=pickle", config_path=existing_config)
    assert len(errors) == 1
    assert "Invalid value 'pickle' for remote-result-mode" in errors[0][0]


def test_port_zero_is_accepted(existing_config: Path) -> None:
    """Port 0 is the standard "let the OS pick one" convention, distinct from the -1 sentinel."""
    result, errors = _parse("port=0", config_path=existing_config)
    assert not errors
    assert result[PORT] == 0


def test_a_learn_path_starting_before_false_alphabetically_is_still_processed(tmp_path: Path) -> None:
    """A non-CLI ``learn=<path>`` rule must be processed as a path, not skipped as if it said
    "false", merely because its value sorts lexically before "false"."""
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse("learn=audit.rules", config_path=rule_file, rule_path=rule_file)
    assert not errors
    assert result[LEARNING_PATH] == rule_file.parent / "audit.rules"
    assert result[LEARN] is True


def test_a_relative_rule_path_defers_a_false_value_to_the_lock_check(tmp_path: Path) -> None:
    """``rule.path != Path(".")`` must be decided by equality, not by path ordering: the lock
    deferral must still trigger for a relative rule path, whatever it sorts against "."."""
    missing_config = tmp_path / "missing.py-sandboxes"
    rules: ConfigLines = [ConfigLine("learn=false", Path("global.profile"), 1)]
    errors: list[ErrorMsg] = []
    parse_rules(missing_config, rules, errors)
    assert len(errors) == 1
    assert "learning mode is forbidden" in errors[0][0]


def test_a_rule_after_a_file_sourced_learn_false_is_still_processed(tmp_path: Path) -> None:
    """The "lock, checked below" skip must ``continue`` to the next rule, not stop the whole loop."""
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse("learn=false", "port=9999", config_path=rule_file, rule_path=rule_file)
    assert result[PORT] == 9999


def test_a_bare_learn_filename_resolves_relative_to_its_own_rule_file(tmp_path: Path) -> None:
    """A bare ``learn=<filename>`` must resolve relative to the file that declares it, not to a
    freshly constructed, never-identical ``Path(".")``."""
    sub = tmp_path / "sub"
    sub.mkdir()
    rule_file = sub / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse("learn=out.rules", config_path=rule_file, rule_path=rule_file)
    assert not errors
    assert result[LEARNING_PATH] == sub / "out.rules"


def test_an_explicit_learn_path_is_honored_even_when_the_target_already_exists(tmp_path: Path) -> None:
    """An explicit ``learn=<path>`` rule must set ``learn`` to True itself, not rely on the "file is
    missing" fallback, which won't fire when the target already exists."""
    target = tmp_path / "out.rules"
    target.write_text("")
    rule_file = tmp_path / CONFIG_NAME
    rule_file.write_text("")
    result, errors = _parse(f"learn={target}", config_path=rule_file, rule_path=rule_file)
    assert not errors
    assert result[LEARN] is True
