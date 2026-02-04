from pathlib import Path

from pysandboxes.guard_envs import parse_rules
from pysandboxes.types import ConfigLine, Envs


def test_simple_env():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=FOO=bar", Path(), 0),
        ],
        Envs({}),
        errors)

    assert env == Envs({"FOO": "bar"})


def test_var_value():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=FOO=${bar}", Path(), 0),
        ],
        Envs({"bar": "BAR"}),
        errors)
    assert env == Envs({"FOO": "BAR"})


def test_var_default_value():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=FOO=${X:=BAR}", Path(), 0),
        ],
        Envs({"bar": "BAR"}),
        errors)
    assert env == Envs({"FOO": "BAR"})


def test_var_pattern():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=*_API_KEY=${*_API_KEY}", Path(), 0),
        ],
        Envs({
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }),
        errors
    )
    assert env == Envs({
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    })


def test_var_all_pattern():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=*=${*}", Path(), 0),
        ],
        Envs({
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }),
        errors
    )
    assert env == Envs({
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    })


def test_var_all_pattern_and_unset():
    errors = []
    _, env, _ = parse_rules(
        [
            ConfigLine("--set-env=*=${*}", Path(), 0),
            ConfigLine("--unset-env=APP1_API_KEY", Path(), 0),
        ],
        Envs({
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }),
        errors
    )
    assert env == Envs({
        "APP2_API_KEY": "456"
    })

# TODO: test activate with os.environ and os.environb
