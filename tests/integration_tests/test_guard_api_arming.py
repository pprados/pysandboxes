# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The API guard must be armed on every user-code entry point.

Uses a minimal profile written per test instead of the shared
``py-sandbox-test.profile``: that profile carries ``net=`` rules
resolving ``ip6-localhost`` and ``www.google.com``, which this
environment cannot resolve (no DNS) and which this test never needs.

Two of the five arming points from task 9 have no test here:

- ``_python_interactive`` (the standalone REPL, no args): driving it
  needs stdin fed to an interactive `code.interact()`/IPython prompt,
  which does not reduce to a `subprocess.run()` with captured output.
  Left to the owner to judge whether that is worth building.
- the SSE handler (``@sandbox``/``sandboxes()``): the sandbox RPC does
  not complete in this environment independently of arming —
  `tests/integration_tests/remote/test_exceptions.py` fails
  identically (2 failed in 279s, zero guard denials) on `ff14342`
  (before this branch existed) and on `b526e5f` (before this task's
  first commit). A test here would fail for a pre-existing,
  unrelated reason, not prove or disprove arming. This is a gap to
  close in an environment where that suite passes, not an oversight.
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


def _run(
    profile: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            *args,
        ],
        cwd=cwd,
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
    # This proves ALLOW resolution, not arming: an inert (never armed)
    # guard would also exit 0 with "0" on stdout. The two deny tests
    # above are what proves arming on this path.
    profile = _write_profile(
        tmp_path,
        "python-api=ALLOW:os.system,posix.system",
    )
    result = _run(profile, "-c", "import os; print(os.system('true'))")
    assert result.returncode == 0, result.stderr
    assert "0" in result.stdout


def test_script_path_denies_os_system(tmp_path: Path) -> None:
    """A bare path argument routes to _python_script, not _python_module."""
    # Reading the script itself goes through the file guard, unlike
    # `-c`, which needs no file access: expose the directory so the
    # script is readable, leaving the API guard as the only thing
    # under test.
    profile = _write_profile(tmp_path, f"expose-ro={tmp_path}")
    module = tmp_path / "boom.py"
    module.write_text("import os\nos.system('true')\n")
    result = _run(profile, str(module))
    assert result.returncode != 0
    assert "denied by the API guard" in result.stderr


def test_module_path_denies_os_system(tmp_path: Path) -> None:
    """`-m <name>` routes to _python_module, via runpy.run_module."""
    # `-m` resolves the module through sys.path; running with cwd set
    # to tmp_path relies on Python inserting "" (cwd) as sys.path[0]
    # for a `-m` invocation, so no PYTHONPATH plumbing is needed.
    profile = _write_profile(tmp_path, f"expose-ro={tmp_path}")
    (tmp_path / "boom_mod.py").write_text("import os\nos.system('true')\n")
    result = _run(profile, "-m", "boom_mod", cwd=tmp_path)
    assert result.returncode != 0
    assert "denied by the API guard" in result.stderr
