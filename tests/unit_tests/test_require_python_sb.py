# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parents[2] / "coding-agents" / "hooks" / "require_python_sb.py"


def run_hook(payload: object) -> subprocess.CompletedProcess[str]:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    "command",
    [
        "python script.py",
        "python3 -m pytest",
        "python3.12 -c 'print(1)'",
        "/usr/bin/python3 script.py",
        "cd src && python script.py",
        "FOO=1 python script.py",
        "ls | python -",
        "make build; python3 x.py",
        "uv run python script.py",
        "uv run --frozen python script.py",
        "uvx python script.py",
        "echo ok\npython script.py",
    ],
)
def test_a_direct_python_is_refused(command: str) -> None:
    result = run_hook({"tool_input": {"command": command}})
    assert result.returncode == 2
    assert "python-sb" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "python-sb script.py",
        "python-sb --pysandboxes-config=skill/.py-sandboxes skill/scripts/report.py",
        "uv run python-sb script.py",
        "uvx python-sb script.py",
        "uvx python-sb --pysandboxes-config=skill/.py-sandboxes skill/scripts/report.py",
        # The commands of the pysandboxes-review-rules and pysandboxes-rules-from-tests skills.
        "cd skill && python-sb --pysandboxes-config=.py-sandboxes scripts/rules_diff.py < /tmp/rules.diff",
        "cd skill && uvx --prerelease allow --find-links https://test.pypi.org/simple/python-sb/ "
        "--find-links https://test.pypi.org/simple/pysandboxes/ python-sb --pysandboxes-config=.py-sandboxes "
        "scripts/rules_diff.py < /tmp/rules.diff",
        'SANDBOX_LEARN=1 pytest -p no:xdist -m sandbox_learn -k "test_export"',
        "uv run pytest -k python",
        'echo "python script.py"',
        "ls python3",
        "git commit -m 'unbalanced",
        "grep -- --learn README.md",
        "python-sb --learning-rate=3 script.py",
    ],
)
def test_other_commands_are_allowed(command: str) -> None:
    result = run_hook({"tool_input": {"command": command}})
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize(
    "command",
    [
        "python-sb --learn script.py",
        "python-sb --learn=other.py-sandboxes script.py",
        "python-sb --pysandboxes-config=skill/.py-sandboxes --learn skill/scripts/report.py",
        "uvx python-sb --learn script.py",
        "uv run python-sb --learn script.py",
        "cd skill && python-sb --learn report.py",
    ],
)
def test_python_sb_in_learning_mode_is_refused(command: str) -> None:
    result = run_hook({"tool_input": {"command": command}})
    assert result.returncode == 2
    assert "--learn" in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Bash", "tool_input": {"command": "python x.py"}},
        {"tool_name": "run_shell_command", "tool_input": {"command": "python x.py"}},
        {"command": "python x.py", "cwd": "/tmp"},
        {"toolName": "bash", "toolArgs": {"command": "python x.py"}},
        {"toolName": "bash", "toolArgs": json.dumps({"command": "python x.py"})},
    ],
    ids=["claude-codex", "gemini", "cursor", "copilot-object", "copilot-string"],
)
def test_the_command_is_found_in_the_input_of_each_agent(payload: dict) -> None:
    assert run_hook(payload).returncode == 2


@pytest.mark.parametrize("payload", ["not json", {"tool_input": {"file_path": "a.py"}}, [1, 2]])
def test_an_input_without_command_is_allowed(payload: object) -> None:
    assert run_hook(payload).returncode == 0
