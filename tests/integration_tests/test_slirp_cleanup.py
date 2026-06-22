# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""slirp4netns must not outlive pysandboxes.

slirp4netns exits when its target process goes away -- but it holds that network
namespace open itself, so once the target is gone it has nothing left to watch and
runs forever, keeping every forwarded port listening on the host. Nothing in the
daemon can clean that up when pysandboxes is killed rather than stopped, so the
launch asks the kernel to do it (PR_SET_PDEATHSIG).
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pysandboxes.remote.tools import unshare_user_namespace_available

from ._env import NO_DEFAULT_ROUTE_REASON, default_route_available

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_STARTUP_TIMEOUT = 120
_CLEANUP_TIMEOUT = 30


def _slirp_pids() -> set[int]:
    """Every running slirp4netns, by pid."""
    result = subprocess.run(["pgrep", "slirp4netns"], capture_output=True, text=True, check=False)
    return {int(line) for line in result.stdout.split()}


def _slirp_target_pid(pid: int) -> int:
    """The pid slirp4netns watches: its next-to-last argument (``<pid> tap0``)."""
    args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
    return int(args[-2])


def _kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_slirp4netns_does_not_outlive_pysandboxes() -> None:
    """Kill the sandbox, then pysandboxes itself: no slirp4netns may be left behind."""
    if not unshare_user_namespace_available():
        pytest.skip("unshare/slirp4netns missing or user namespaces not permitted")
    if not default_route_available():
        pytest.skip(NO_DEFAULT_ROUTE_REASON)

    env = os.environ.copy()
    env["OS_SANDBOX"] = "unshare"
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"

    before = _slirp_pids()
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.integration_tests.tst_hold_sandbox"],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawned: set[int] = set()
    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            spawned = _slirp_pids() - before
            if spawned:
                break
            if process.poll() is not None:
                pytest.fail(f"the sandbox exited with code {process.returncode} before slirp4netns started")
            time.sleep(0.5)
        assert spawned, f"unshare started no slirp4netns within {_STARTUP_TIMEOUT}s"

        # Kill the watched process first: slirp4netns then has no exit trigger left of
        # its own, which is the state where it used to survive its whole parent tree.
        for pid in spawned:
            _kill(_slirp_target_pid(pid))
        time.sleep(1)

        process.kill()
        process.wait(timeout=_CLEANUP_TIMEOUT)

        deadline = time.monotonic() + _CLEANUP_TIMEOUT
        while time.monotonic() < deadline and _slirp_pids() & spawned:
            time.sleep(0.5)

        assert not (_slirp_pids() & spawned), (
            "slirp4netns outlived pysandboxes: it holds the sandbox network namespace, "
            "and every port forwarded into it, alive on the host"
        )
    finally:
        if process.poll() is None:
            process.kill()
        for pid in _slirp_pids() & spawned:
            _kill(pid)
