# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The ``python-sb`` command line through each backend: what it runs, what it returns, what it refuses.

Each case starts ``python -m pysandboxes.python_sb`` as the user does. QEMU boots a VM per run, so the rows
that only prove the command line leave it out: ``test_guards_with_providers`` already runs it end to end.
"""

import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, coverage_profile_lines, os_sandbox_params, row_profile_lines
from .test_guards_with_providers import _INTERPRETER_PATHS, _TIMEOUT_SECONDS, ROOT_DIR, _skip_unavailable

_ROWS = [row for row in os_sandbox_params() if not str(row.values[0]).startswith("qemu")]


def _python_sb(
    os_sandbox: str, profile_lines: str, args: list[str], tmp_path: Path, stdin: str | None = None
) -> "subprocess.CompletedProcess[str]":
    profile = tmp_path / "cli.profile"
    exposed = "".join(f"expose-ro={path}\n" for path in (str(tmp_path), *_INTERPRETER_PATHS))
    profile.write_text(
        f"py-sandbox=true\nos-sandbox={backend_of(os_sandbox)}\n{row_profile_lines(os_sandbox)}{exposed}{coverage_profile_lines()}{profile_lines}"
    )
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", *args],
        cwd=ROOT_DIR,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_command_string_runs_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)

    done = _python_sb(os_sandbox, "python-import=*\n", ["-c", "print(6 * 7)"], tmp_path)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "42"


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_module_runs_with_its_arguments_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)

    done = _python_sb(os_sandbox, "python-import=*\n", ["-m", "timeit", "-n", "1", "-r", "1", "pass"], tmp_path)

    assert done.returncode == 0, done.stderr
    assert "1 loop, best of 1" in done.stdout


def test_a_module_already_imported_by_the_framework_runs_with_m(tmp_path: Path) -> None:
    done = _python_sb("subprocess", "python-import=*\n", ["-m", "calendar", "2026", "10"], tmp_path)

    assert done.returncode == 0, done.stderr
    assert "October 2026" in done.stdout


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_script_read_from_stdin_runs_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)

    done = _python_sb(os_sandbox, "python-import=*\n", ["-"], tmp_path, stdin="print('from stdin')\n")

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "from stdin"


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_the_exit_status_of_the_script_is_the_one_returned(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)

    done = _python_sb(os_sandbox, "python-import=*\n", ["-c", "import sys; sys.exit(7)"], tmp_path)

    assert done.returncode == 7, done.stderr


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_rule_on_the_command_line_reaches_the_script(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)

    done = _python_sb(
        os_sandbox,
        "python-import=*\n",
        ["--env=FROM_THE_COMMAND_LINE=yes", "-c", "import os; print(os.environ.get('FROM_THE_COMMAND_LINE'))"],
        tmp_path,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "yes"


def test_the_version_is_printed_without_running_anything(tmp_path: Path) -> None:
    done = _python_sb("subprocess", "", ["--version"], tmp_path)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "Python " + ".".join(map(str, sys.version_info[:3]))


def test_a_rule_the_profile_does_not_know_is_refused_before_anything_runs(tmp_path: Path) -> None:
    done = _python_sb("subprocess", "no-such-rule=1\n", ["-c", "print('ran')"], tmp_path)

    assert done.returncode != 0
    assert "no-such-rule" in done.stderr
    assert "ran" not in done.stdout


def test_a_locked_profile_refuses_a_rule_on_the_command_line(tmp_path: Path) -> None:
    done = _python_sb("subprocess", "learn=false\n", ["--env=X=1", "-c", "print('ran')"], tmp_path)

    assert done.returncode != 0
    assert "locks the rules" in done.stderr
    assert "ran" not in done.stdout
