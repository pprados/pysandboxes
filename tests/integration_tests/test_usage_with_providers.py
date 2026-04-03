"""
Integration tests: invoke tst_usage via subprocess with each OS sandbox provider.

Similar to tests/containers/test_containers.py but without containers: runs
python-sb -m tests.integration_tests.tst_usage with OS_SANDBOX set to each
provider. Success is determined by the exit code of the launched process (0 = success).
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pysandboxes.remote.landlock_daemon import landlock_user_available
from pysandboxes.remote.tools import unshare_user_namespace_available, which_command

logger = logging.getLogger(__name__)

# Project root (parent of tests/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

PYTHON_SB_ARGS = "--pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

# All OS sandbox providers to test (no container); skip conditions applied per provider
all_os_sandbox: list[str] = [
    "subprocess",
    "unshare",
    "firejail",
    "landlock",
]


def _run_tst_usage(os_sandbox: str) -> subprocess.CompletedProcess:
    """Run tst_usage via python-sb with the given OS_SANDBOX provider."""
    env = os.environ.copy()
    env["OS_SANDBOX"] = os_sandbox.lower()
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "pysandboxes.python_sb",
        PYTHON_SB_ARGS,
        "-m",
        "tests.integration_tests.tst_usage",
    ]

    return subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _skip_reason(os_sandbox: str) -> str | None:
    """Return skip reason for provider if unavailable, else None."""
    if os_sandbox == "firejail" and not which_command("firejail"):
        return "firejail not installed"
    if os_sandbox == "unshare" and not unshare_user_namespace_available():
        return "unshare/slirp4netns missing or user namespaces not permitted"
    if os_sandbox == "landlock" and not landlock_user_available():
        return "Landlock not available (kernel < 5.13 or not Linux)"
    return None


@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
def test_usage_with_provider(os_sandbox: str) -> None:
    """Run tst_usage via python-sb for each OS sandbox provider; success = exit code 0."""
    reason = _skip_reason(os_sandbox)
    if reason:
        pytest.skip(reason)

    result = _run_tst_usage(os_sandbox)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    assert (
        result.returncode == 0
    ), f"tst_usage (os_sandbox={os_sandbox}) exited with code {result.returncode}"
