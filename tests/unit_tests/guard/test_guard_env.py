from pathlib import Path
from typing import List

from pysandboxes.guard_envs import parse_rules
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


# TODO: test activate with os.environ and os.environb
