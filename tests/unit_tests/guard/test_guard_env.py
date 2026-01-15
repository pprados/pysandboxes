from pysandboxes.guard_env import parse_guard_envs


def test_simple_env():
    env, _ = parse_guard_envs([
        "--set-env=FOO=bar"
    ], {})
    assert env == {"FOO": "bar"}


def test_var_value():
    env, _ = parse_guard_envs([
        "--set-env=FOO=${bar}"
    ], {"bar": "BAR"})
    assert env == {"FOO": "BAR"}


def test_var_default_value():
    env, _ = parse_guard_envs([
        "--set-env=FOO=${X:=BAR}"
    ], {"bar": "BAR"})
    assert env == {"FOO": "BAR"}


def test_var_pattern():
    env, _ = parse_guard_envs([
        "--set-env=*_API_KEY=${*_API_KEY}"
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }
    )
    assert env == {
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    }


def test_var_all_pattern():
    env, _ = parse_guard_envs([
        "--set-env=*=${*}"
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }
    )
    assert env == {
        "APP1_API_KEY": "123",
        "APP2_API_KEY": "456"
    }


def test_var_all_pattern_and_unset():
    env, _ = parse_guard_envs([
        "--set-env=*=${*}",
        "--unset-env=APP1_API_KEY",
    ],
        {
            "APP1_API_KEY": "123",
            "APP2_API_KEY": "456"
        }
    )
    assert env == {
        "APP2_API_KEY": "456"
    }
