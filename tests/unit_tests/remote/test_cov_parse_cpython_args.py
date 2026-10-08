# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Command lines CPython accepts and ``python-sb`` should split the same way.

Each test states what CPython does with the command line.
"""

import subprocess
import sys

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote.parse_cpython_args import parse_python_cmd_line


def _command(run_args: list[str]) -> str:
    """``-m json.tool`` and ``-mjson.tool`` name the same command."""
    return "".join(run_args[:2])


def test_a_separate_module_switch_is_the_command() -> None:
    python_args, sandbox_args, run_args, _ = parse_python_cmd_line(["-B", "--learn", "-m", "json.tool", "-h"])

    assert python_args == ["-B"]
    assert sandbox_args == ["--learn"]
    assert run_args == ["-m", "json.tool", "-h"]


def test_options_after_the_script_belong_to_the_script() -> None:
    python_args, sandbox_args, run_args, _ = parse_python_cmd_line(["-B", "x.py", "-v", "--learn"])

    assert python_args == ["-B"]
    assert sandbox_args == []
    assert run_args == ["x.py", "-v", "--learn"]


def test_a_module_glued_to_its_switch_is_the_command() -> None:
    _, _, run_args, _ = parse_python_cmd_line(["-mjson.tool"])

    assert _command(run_args) == "-mjson.tool"


def test_a_program_glued_to_its_switch_is_the_command() -> None:
    _, _, run_args, _ = parse_python_cmd_line(["-cprint(1)"])

    assert _command(run_args) == "-cprint(1)"


def test_a_module_switch_grouped_with_a_flag_is_the_command() -> None:
    python_args, _, run_args, _ = parse_python_cmd_line(["-Im", "json.tool"])

    assert _command(run_args) == "-mjson.tool"
    assert "-I" in python_args or "-Im" in python_args


def test_a_script_without_the_py_suffix_is_the_command() -> None:
    python_args, _, run_args, _ = parse_python_cmd_line(["-B", "myscript", "arg"])

    assert python_args == ["-B"]
    assert run_args == ["myscript", "arg"]


def test_a_trailing_config_switch_without_its_value_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_python_cmd_line(["--pysandboxes-config"])

    assert exit_info.value.code == 2


def test_a_module_command_parses_in_a_fresh_interpreter() -> None:
    code = (
        "from pysandboxes.remote.parse_cpython_args import parse_python_cmd_line\n"
        "print(parse_python_cmd_line(['-m', 'json.tool'])[2])"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "['-m', 'json.tool']"
