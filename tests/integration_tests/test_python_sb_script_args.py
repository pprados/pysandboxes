# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``python-sb script.py --help`` must hand ``--help`` to the script.

The sandboxed child is started as ``main_sandbox <script> <args> --_named-pipe ...``,
and its own parser answered ``-h``/``--help``: it printed the internal usage and
exited before reading its configuration, so the script never ran.
"""

import subprocess
import sys
from pathlib import Path

import pytest


def _python_sb(tmp_path: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    profile = tmp_path / "args.profile"
    profile.write_text(f"py-sandbox=true\nos-sandbox=subprocess\npython-import=*\nexpose-ro={tmp_path}\n")
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", str(script), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("arg", ["--help", "-h", "--_n"])
def test_script_arguments_reach_the_script(tmp_path: Path, arg: str) -> None:
    script = tmp_path / "echo_args.py"
    script.write_text("import sys\nprint('ARGS', sys.argv[1:])\n")

    result = _python_sb(tmp_path, script, arg)

    assert result.returncode == 0, result.stderr
    assert f"ARGS ['{arg}']" in result.stdout


def test_a_missing_script_exits_like_cpython(tmp_path: Path) -> None:
    result = _python_sb(tmp_path, tmp_path / "missing.py")

    assert result.returncode == 2, result.stderr
    assert "can't open file" in result.stderr
