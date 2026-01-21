from pathlib import Path

from pysandboxes.guard_env import parse_guard_envs
from pysandboxes.types import ConfigLine


def test_simple_env():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=FOO=bar", Path(), 0),
    ], {},
        errors)
    assert env == {"FOO": "bar"}


def test_var_value():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=FOO=${bar}", Path(), 0),
    ], {"bar": "BAR"}, errors)
    assert env == {"FOO": "BAR"}


def test_var_default_value():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=FOO=${X:=BAR}", Path(), 0),
    ], {"bar": "BAR"},errors)
    assert env == {"FOO": "BAR"}


def test_var_pattern():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=*_API_KEY=${*_API_KEY}", Path(), 0),
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        },
        errors
    )
    assert env == {
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    }


def test_var_all_pattern():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=*=${*}", Path(), 0),
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        },
        errors
    )
    assert env == {
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    }


def test_var_all_pattern_and_unset():
    errors = []
    env, _ = parse_guard_envs([
        ConfigLine("--set-env=*=${*}", Path(), 0),
        ConfigLine("--unset-env=APP1_API_KEY", Path(), 0),
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        },
        errors
    )
    assert env == {
        "APP2_API_KEY": "456"
    }
