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

from ._env import (
    ALL_OS_SANDBOX,
    NO_DEFAULT_ROUTE_REASON,
    NO_PROFILE_DNS_REASON,
    backend_of,
    default_route_available,
    os_sandbox_params,
    profile_hosts_resolvable,
    provider_skip_reason,
)
from .tst_usage import SECRET_ENV

logger = logging.getLogger(__name__)

# Project root (parent of tests/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

PYTHON_SB_ARGS = "--pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

# All OS sandbox providers to test (no container); skip conditions applied per provider.
# A provider whose binary is missing skips itself, see _skip_reason, so this list
# stays portable. Shared with test_guards_with_providers, so both suites cover the
# same set and neither drifts.
all_os_sandbox: list[str] = list(ALL_OS_SANDBOX)


def _run_tst_usage(os_sandbox: str) -> subprocess.CompletedProcess:
    """Run tst_usage via python-sb with the given OS_SANDBOX provider."""
    env = os.environ.copy()
    backend = backend_of(os_sandbox)
    env["OS_SANDBOX"] = backend.lower()
    # The shared profile reads it as qemu.use_kvm; the "qemu-tcg" row is the same
    # backend with acceleration refused, which is what a container without /dev/kvm
    # gets. Set for every row, so the value never leaks in from the caller's shell.
    env["QEMU_USE_KVM"] = "false" if os_sandbox == "qemu-tcg" else "true"
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
    timeout = 600 if backend == "qemu" else 120

    return subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _skip_reason(os_sandbox: str) -> str | None:
    """Return skip reason for provider if unavailable, else None.

    The two checks here belong to *this* scenario -- ``tst_usage`` drives the network
    through the profile's ``net=`` rules -- while the backend's own availability is
    shared with the other per-provider suites.
    """
    if not profile_hosts_resolvable():
        return NO_PROFILE_DNS_REASON
    if os_sandbox in ("firejail", "unshare") and not default_route_available():
        return NO_DEFAULT_ROUTE_REASON
    return provider_skip_reason(os_sandbox)


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
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
# its setup stage needs the host PATH; it now narrows os.environ down to the profile's
# whitelist just before exec'ing the daemon, which is why this row is no longer xfail.
# QEMU partial mode runs the daemon in the VM. It used to fail on the configuration
# transport, not on any timeout; with the config on the 9p mount the KVM row passes in
# ~22s. The emulated row is left: measured with both caps lifted, the guest answers at
# ~125s, above TIMEOUT_FOR_START_DAEMON_QEMU (90s) and past QEMU_LOOP_FOR_PING (200
# attempts). It is run rather than declared -- it now costs ~105s to fail, and a row that
# never runs would not say when the limitation lifts.
_PARTIAL_MODE_XFAIL: dict[str, tuple[str, bool]] = {
    "qemu-tcg": ("without KVM the guest answers at ~125s, past the 90s daemon start cap", True),
}


def _partial_mode_params() -> list:
    """One row per provider; the two known holes are declared xfail instead of hidden."""
    rows = []
    for os_sandbox in all_os_sandbox:
        marks = []
        if os_sandbox in _PARTIAL_MODE_XFAIL:
            reason, run = _PARTIAL_MODE_XFAIL[os_sandbox]
            marks.append(pytest.mark.xfail(reason=reason, run=run, strict=True))
        if os_sandbox == "qemu-tcg":
            marks.append(pytest.mark.slow)
        rows.append(pytest.param(os_sandbox, marks=marks))
    return rows


def _run_partial_mode(os_sandbox: str) -> subprocess.CompletedProcess:
    """Run tst_env_leak with a plain interpreter, so the parent keeps its real environment."""
    env = os.environ.copy()
    backend = backend_of(os_sandbox)
    env["OS_SANDBOX"] = backend.lower()
    env["QEMU_USE_KVM"] = "false" if os_sandbox == "qemu-tcg" else "true"
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"
    env["SECRET_TOKEN"] = PARTIAL_MODE_SECRET

    timeout = 600 if backend == "qemu" else 120

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
