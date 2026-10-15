# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a real bwrap process can reach on the host."""

import os
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote.bwrap_sse_daemon import BWrapSSEDaemon

from .._env import provider_skip_reason

_BWRAP_SKIP_REASON = provider_skip_reason("bwrap") or ""


@pytest.mark.skipif(provider_skip_reason("bwrap") is not None, reason=_BWRAP_SKIP_REASON)
def test_run_user_bus_is_not_reachable_from_inside_bwrap(tmp_path: Path) -> None:
    """NR1: binding the whole of /run exposed every /run/user/<uid>, including this user's session
    D-Bus bus (answers AUTH EXTERNAL OK from inside the sandbox -- a host escape). A real bwrap
    process must not be able to reach it.
    """
    args = BWrapSSEDaemon("token")._bwrap_args(EmptyRules, dict(os.environ), tmp_path / "pipe", tmp_path)
    probe = args + [
        "--",
        sys.executable,
        "-c",
        f"import os, sys; sys.exit(1 if os.path.exists('/run/user/{os.getuid()}/bus') else 0)",
    ]
    result = subprocess.run(probe, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
