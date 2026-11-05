# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A sandbox must not leave temporary files behind.

Every run used to drop at least one empty directory in the system temporary
directory -- ``activate_sandboxes`` made one per sandboxed process and never
removed it -- and an ``unshare`` run added its chroot root, a ``.resolv``, a
``.hosts``, the slirp4netns pid file and its API socket. None of them is large;
they accumulate in the thousands over a test campaign, until the disk complains.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from pysandboxes._os_sandbox import unsupported_platform_reason

from ._env import (
    NO_DEFAULT_ROUTE_REASON,
    NO_PROFILE_DNS_REASON,
    default_route_available,
    profile_hosts_resolvable,
    provider_skip_reason,
    backend_of,
    qemu_tcg_requested,
)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_RUN_TIMEOUT = 300


def _temp_entries() -> set[str]:
    """Every ``tmp*`` entry in the system temporary directory, by name."""
    tmp_dir = Path(tempfile.gettempdir())
    return {name for name in os.listdir(tmp_dir) if name.startswith(("tmp", "pysandboxes-qemu-"))}


# A provider the platform does not have gets no row: with PYSANDBOXES_FAIL_ON_SKIP a skip fails the run.
_PROVIDERS = [
    name
    for name in (
        "subprocess",
        "unshare",
        "appcontainer",
        "qemu-microvm",
        *(("qemu-microvm-tcg",) if qemu_tcg_requested() else ()),
    )
    if not unsupported_platform_reason(backend_of(name))
]


@pytest.mark.parametrize("os_sandbox", _PROVIDERS)
def test_a_sandbox_leaves_no_temporary_file_behind(os_sandbox: str) -> None:
    """Run one sandbox to completion: the temporary directory must look untouched."""
    reason = provider_skip_reason(os_sandbox)
    if reason:
        pytest.skip(reason)
    if os_sandbox not in ("subprocess", "appcontainer") and not default_route_available():
        pytest.skip(NO_DEFAULT_ROUTE_REASON)
    if not profile_hosts_resolvable():
        pytest.skip(NO_PROFILE_DNS_REASON)

    env = os.environ.copy()
    env["OS_SANDBOX"] = backend_of(os_sandbox)
    env["QEMU_USE_KVM"] = "false" if os_sandbox.endswith("-tcg") else "true"
    env.setdefault("TERM", "dumb")
    env["My_ENV"] = "1"

    before = _temp_entries()
    qemu_before = _qemu_pids() if os_sandbox.startswith("qemu") else set()
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_resolve_once"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=900 if os_sandbox.startswith("qemu") else _RUN_TIMEOUT,
        check=False,
    )
    assert "RESOLVED" in result.stdout, f"the sandbox could not resolve a hostname:\n{result.stderr}"

    if os_sandbox.startswith("qemu"):
        assert not _qemu_pids() - qemu_before, "QEMU survived sandbox shutdown"

    left = _temp_entries() - before
    assert not left, f"{os_sandbox} left {len(left)} temporary entries behind: {sorted(left)}"


def _qemu_pids() -> set[int]:
    """Find QEMU processes so exit cannot silently leak a guest."""
    found = set()
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                executable = (entry / "exe").resolve().name
                if executable.startswith("qemu-system-"):
                    found.add(int(entry.name))
            except OSError:
                continue
    return found
