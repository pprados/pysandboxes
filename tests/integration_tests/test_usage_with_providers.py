"""
Integration tests: invoke tst_usage via subprocess with each OS sandbox provider.

Similar to tests/containers/test_containers.py but without containers: runs
python-sb -m tests.integration_tests.tst_usage with OS_SANDBOX set to each
provider. Success is determined by the exit code of the launched process (0 = success).
"""

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from pysandboxes.remote.landlock_daemon import landlock_user_available
from pysandboxes.remote.tools import unshare_user_namespace_available, which_command

from ._env import (
    NO_DEFAULT_ROUTE_REASON,
    NO_PROFILE_DNS_REASON,
    default_route_available,
    profile_hosts_resolvable,
)

logger = logging.getLogger(__name__)

# Project root (parent of tests/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

PYTHON_SB_ARGS = "--pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

# All OS sandbox providers to test (no container); skip conditions applied per provider.
# A provider whose binary is missing skips itself, see _skip_reason, so this list
# stays portable.
all_os_sandbox: list[str] = [
    "subprocess",
    "qemu",
    "unshare",
    "firejail",
    "landlock",
    "bwrap",
]

# TODO: test with split mode


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
    # qemu needs time for VM boot + cloud-init + bootstrap
    timeout = 600 if os_sandbox == "qemu" else 120

    return subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _skip_reason(os_sandbox: str) -> str | None:
    """Return skip reason for provider if unavailable, else None."""
    if not profile_hosts_resolvable():
        return NO_PROFILE_DNS_REASON
    if os_sandbox in ("firejail", "unshare") and not default_route_available():
        return NO_DEFAULT_ROUTE_REASON
    if os_sandbox == "firejail" and not which_command("firejail"):
        return "firejail not installed"
    if os_sandbox == "unshare" and not unshare_user_namespace_available():
        return "unshare/slirp4netns missing or user namespaces not permitted"
    if os_sandbox == "landlock" and not landlock_user_available():
        return "Landlock not available (kernel < 5.13 or not Linux)"
    if os_sandbox == "bwrap" and not which_command("bwrap"):
        return "bwrap not installed"
    if os_sandbox == "qemu":
        arch = platform.machine()
        if not which_command(f"qemu-system-{arch}") and not which_command("qemu-system-x86_64"):
            return "QEMU not installed"
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
    assert result.returncode == 0, f"tst_usage (os_sandbox={os_sandbox}) exited with code {result.returncode}"
