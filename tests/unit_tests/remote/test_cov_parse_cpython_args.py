# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Command lines CPython accepts and ``python-sb`` should split the same way.

Each test states what CPython does with the command line.
"""

import subprocess
import sys
from pathlib import Path

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


def test_a_module_command_looks_up_the_config_of_its_module(monkeypatch: pytest.MonkeyPatch) -> None:
    looked_up: list[str] = []

    def find(module: str, config: str) -> Path:
        looked_up.append(module)
        return Path("/configs/pkg/.py-sandboxes")

    monkeypatch.setattr("pysandboxes.remote.parse_cpython_args.find_config_for_module", find)

    assert parse_python_cmd_line(["-m", "pkg.mod"])[3] == Path("/configs/pkg/.py-sandboxes")
    assert parse_python_cmd_line(["-m", "pkg.mod", "arg"])[3] == Path("/configs/pkg/.py-sandboxes")
    assert looked_up == ["pkg.mod", "pkg.mod"]


def test_a_script_command_does_not_look_up_a_module_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def find(module: str, config: str) -> Path:
        raise AssertionError(f"looked up {module}")

    monkeypatch.setattr("pysandboxes.remote.parse_cpython_args.find_config_for_module", find)

    parse_python_cmd_line(["script.py", "pkg.mod"])
