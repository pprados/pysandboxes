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
from .tst_usage import SECRET_ENV

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


def _run_tst_usage(os_sandbox: str) -> subprocess.CompletedProcess:
    """Run tst_usage via python-sb with the given OS_SANDBOX provider."""
    env = os.environ.copy()
    env["OS_SANDBOX"] = os_sandbox.lower()
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"
    # No rule whitelists this, so tst_usage fails if the sandbox can see it.
    env[SECRET_ENV] = "must-not-reach-the-sandbox"

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


# --- Partial mode (the README's "split mode": only the @sandbox functions are isolated) ---

# Partial mode is the mode where the leak matters: the application keeps every privilege it
# has, API tokens included, and only the sandboxed part must be blind to them. python-sb
# strips os.environ before spawning anything, so complete mode hides a leak in the spawn
# path itself -- the parent it spawns from is already clean. A plain interpreter does not.
PARTIAL_MODE_SECRET = "s3cr3t-do-not-leak"

# unshare builds its namespaces, mounts and iptables rules *before* the sandbox exists, so
# its setup stage needs the host PATH; it then execs the daemon with that same environment
# (unshare_setup.py) and the whitelist never reaches the sandbox.
# QEMU partial mode boots the VM past the 30s configuration timeout; declared, not run,
# because the row costs ten minutes to fail.
_PARTIAL_MODE_XFAIL: dict[str, tuple[str, bool]] = {
    "unshare": ("unshare_setup execs the sandbox daemon with the host environment", True),
    "qemu": ("partial mode exceeds the 30s configuration timeout while the VM boots", False),
}


def _partial_mode_params() -> list:
    """One row per provider; the two known holes are declared xfail instead of hidden."""
    rows = []
    for os_sandbox in all_os_sandbox:
        marks = []
        if os_sandbox in _PARTIAL_MODE_XFAIL:
            reason, run = _PARTIAL_MODE_XFAIL[os_sandbox]
            marks.append(pytest.mark.xfail(reason=reason, run=run, strict=True))
        rows.append(pytest.param(os_sandbox, marks=marks))
    return rows


def _run_partial_mode(os_sandbox: str) -> subprocess.CompletedProcess:
    """Run tst_env_leak with a plain interpreter, so the parent keeps its real environment."""
    env = os.environ.copy()
    env["OS_SANDBOX"] = os_sandbox.lower()
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"
    env["SECRET_TOKEN"] = PARTIAL_MODE_SECRET

    timeout = 600 if os_sandbox == "qemu" else 120

    return subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_env_leak"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.parametrize("os_sandbox", _partial_mode_params())
def test_partial_mode_hides_the_parent_environment(os_sandbox: str) -> None:
    """In partial mode the sandbox sees the variables the profile whitelists, and nothing else."""
    reason = _skip_reason(os_sandbox)
    if reason:
        pytest.skip(reason)

    result = _run_partial_mode(os_sandbox)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    assert PARTIAL_MODE_SECRET not in (result.stdout + result.stderr), "the secret must not be logged"
    assert result.returncode == 0, (
        f"partial mode (os_sandbox={os_sandbox}) exited with code {result.returncode}: "
        "the sandbox saw an environment variable no rule whitelists"
    )
