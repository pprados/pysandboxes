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
