# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""In CI, a skipped integration test is a test that did not run, and the run must say so.

With ``PYSANDBOXES_FAIL_ON_SKIP=1`` the integration conftest lets the whole session
run -- so the report shows what passes and what does not -- then fails it at the end
and lists every skip with its reason.
"""

import os
import subprocess
import sys
from pathlib import Path

_CONFTEST = Path(__file__).parents[1] / "integration_tests" / "conftest.py"

_SUITE = """
import pytest

def test_runs():
    pass

def test_cannot_run_here():
    pytest.skip("bwrap not installed")

@pytest.mark.xfail(reason="known")
def test_known_failure():
    raise AssertionError
"""


def _run(tmp_path: Path, suite: str, fail_on_skip: bool) -> subprocess.CompletedProcess[str]:
    (tmp_path / "conftest.py").write_text(_CONFTEST.read_text())
    (tmp_path / "test_suite.py").write_text(suite)
    env = {k: v for k, v in os.environ.items() if k != "PYSANDBOXES_FAIL_ON_SKIP"}
    if fail_on_skip:
        env["PYSANDBOXES_FAIL_ON_SKIP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--color=no", str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_skips_fail_the_run_at_the_end(tmp_path: Path) -> None:
    result = _run(tmp_path, _SUITE, fail_on_skip=True)

    assert "1 passed, 1 skipped, 1 xfailed" in result.stdout, "every test must still run"
    assert result.returncode == 1
    assert "test_cannot_run_here: bwrap not installed" in result.stdout


def test_without_the_variable_a_skip_stays_a_skip(tmp_path: Path) -> None:
    result = _run(tmp_path, _SUITE, fail_on_skip=False)

    assert "1 passed, 1 skipped, 1 xfailed" in result.stdout
    assert result.returncode == 0


def test_a_run_without_skip_stays_green(tmp_path: Path) -> None:
    result = _run(tmp_path, "def test_runs():\n    pass\n", fail_on_skip=True)

    assert result.returncode == 0
