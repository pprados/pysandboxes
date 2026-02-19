from pysandboxes.remote.python_in_sb import convert_extra_rules


def test_convert_extra_rules() -> None:
    assert convert_extra_rules(["--a=1"]) == {"a": {"1"}}
    assert convert_extra_rules(["--a=1", "--a=2"]) == {"a": {"1", "2"}}
    assert convert_extra_rules(["--a=1", "--b=2"]) == {"a": {"1"}, "b": {"2"}}
