# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The API guard must be armed on every user-code entry point.

Uses a minimal profile written per test instead of the shared
``py-sandbox-test.profile``: that profile carries ``net=`` rules
resolving ``ip6-localhost`` and ``www.google.com``, which this
environment cannot resolve (no DNS) and which this test never needs.
"""

import subprocess
import sys
from pathlib import Path


def _write_profile(tmp_path: Path, *extra_lines: str) -> Path:
    profile = tmp_path / "arming.profile"
    profile.write_text(
        "py-sandbox=true\n"
        "os-sandbox=subprocess\n"
        "python-import=*\n" + "".join(f"{line}\n" for line in extra_lines)
    )
    return profile


def _run(profile: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_command_path_denies_os_system(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path)
    result = _run(profile, "-c", "import os; os.system('true')")
    assert result.returncode != 0
    assert "denied by the API guard" in result.stderr


def test_command_path_denies_the_posix_alias(tmp_path: Path) -> None:
    """posix.system is the same object as os.system."""
    profile = _write_profile(tmp_path)
    result = _run(profile, "-c", "import posix; posix.system('true')")
    assert result.returncode != 0
    assert "denied by the API guard" in result.stderr


def test_command_path_allows_an_explicit_function(tmp_path: Path) -> None:
    # main_sandbox.py's __main__ block calls os._exit() unconditionally
    # after python_in_sb() returns, i.e. after arm(): every `-c`/`-m`/
    # script run needs this allowed to exit cleanly once armed (see
    # the report for task 10).
    profile = _write_profile(
        tmp_path,
        "python-api=ALLOW:os.system,posix.system,os._exit",
    )
    result = _run(profile, "-c", "import os; print(os.system('true'))")
    assert result.returncode == 0, result.stderr
    assert "0" in result.stdout


def test_module_path_denies_os_system(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path)
    module = tmp_path / "boom.py"
    module.write_text("import os\nos.system('true')\n")
    result = _run(profile, str(module))
    assert result.returncode != 0
    assert "denied by the API guard" in result.stderr
