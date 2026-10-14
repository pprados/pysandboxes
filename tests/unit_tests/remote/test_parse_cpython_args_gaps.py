# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Where the python-sb command line stops being CPython's options, and how its own options are read."""

from pathlib import Path

import pytest

from pysandboxes.remote.parse_cpython_args import parse_python_cmd_line


@pytest.mark.parametrize(
    ("argv", "python_args", "run_args"),
    [
        (["-Im", "json.tool", "x"], ["-I"], ["-m", "json.tool", "x"]),
        (["-mjson.tool"], [], ["-m", "json.tool"]),
        (["-cimport sys; print(1)", "a"], [], ["-c", "import sys; print(1)", "a"]),
        (["-Wignore", "script.py"], ["-Wignore"], ["script.py"]),
        (["-Wcm", "x.py"], ["-Wcm"], ["x.py"]),
        (["-W", "ignore", "s.py"], ["-W", "ignore"], ["s.py"]),
    ],
)
def test_the_split_between_cpython_options_and_the_program(
    argv: list[str], python_args: list[str], run_args: list[str]
) -> None:
    parsed, sandboxes, run, _ = parse_python_cmd_line(argv)

    assert parsed == python_args
    assert run == run_args
    assert sandboxes == []


class TestPysandboxesConfigOption:
    def test_the_last_config_wins(self) -> None:
        argv = ["--pysandboxes-config", "a.profile", "--pysandboxes-config=b.profile", "s.py"]

        _, _, run, config = parse_python_cmd_line(argv)

        assert config == Path("b.profile")
        assert run == ["s.py"]

    def test_the_value_of_the_option_is_never_read_as_an_option(self) -> None:
        _, _, run, config = parse_python_cmd_line(["--pysandboxes-config", "--pysandboxes-config=x", "s.py"])

        assert config == Path("--pysandboxes-config=x")
        assert run == ["s.py"]

    def test_a_bare_learn_writes_to_the_named_config(self) -> None:
        _, sandboxes, _, _ = parse_python_cmd_line(["--pysandboxes-config=n.profile", "--aaa", "--learn", "s.py"])

        assert sandboxes == ["--aaa", "--learn=n.profile"]

    def test_a_bare_learn_without_a_named_config_stays_bare(self) -> None:
        _, sandboxes, _, _ = parse_python_cmd_line(["--learn", "s.py"])

        assert sandboxes == ["--learn"]


def test_the_help_is_wrapped_at_80_columns_whatever_the_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLUMNS", "300")

    with pytest.raises(SystemExit):
        parse_python_cmd_line(["--help"])

    assert max(len(line) for line in capsys.readouterr().out.splitlines()) <= 80
