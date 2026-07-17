from pysandboxes.remote.python_in_sb import convert_extra_rules


def test_convert_extra_rules() -> None:
    assert convert_extra_rules(["--a=1"]) == {"a": {"1"}}
    assert convert_extra_rules(["--a=1", "--a=2"]) == {"a": {"1", "2"}}
    assert convert_extra_rules(["--a=1", "--b=2"]) == {"a": {"1"}, "b": {"2"}}


def test_parse_config_collects_the_eval_profiles() -> None:
    from pathlib import Path

    from pysandboxes.py_sandbox import parse_config
    from pysandboxes.sb_types import ConfigLine

    config = [
        ConfigLine("py-sandbox=true", Path("profile"), 0),
        ConfigLine("eval-syntax=arith", Path("profile"), 1),
        ConfigLine("eval-timeout:llm=2s", Path("profile"), 2),
    ]
    all_rules = parse_config(config, Path("profile"), envs={})
    assert all_rules.eval_rules[""].syntax.allows("BinOp")  # type: ignore[union-attr]
    assert all_rules.eval_rules["llm"].timeout == 2.0  # type: ignore[union-attr]


def test_parse_config_without_eval_keys_leaves_the_profiles_empty() -> None:
    from pathlib import Path

    from pysandboxes.py_sandbox import parse_config
    from pysandboxes.sb_types import ConfigLine

    all_rules = parse_config([ConfigLine("py-sandbox=true", Path("profile"), 0)], Path("profile"), envs={})
    assert not all_rules.eval_rules


def test_an_unknown_eval_key_fails_the_configuration() -> None:
    from pathlib import Path

    import pytest  # type: ignore[import-untyped]

    from pysandboxes.e import ConfigSyntaxError
    from pysandboxes.py_sandbox import parse_config
    from pysandboxes.sb_types import ConfigLine

    config = [ConfigLine("eval-nodes=10", Path("profile"), 0)]
    with pytest.raises(ConfigSyntaxError):
        parse_config(config, Path("profile"), envs={})
