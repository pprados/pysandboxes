# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``unshare`` without a ``/proc`` (``unshare.proc=none``) still resolves a ``dir_fd``.

The file guard reads ``/proc/self/fd/N`` to know which directory a descriptor names. With no ``/proc`` it
resolves the descriptor from the path it recorded when ``os.open`` returned it.
"""

import os
import subprocess
import sys
from pathlib import Path

from ._env import (
    NO_DEFAULT_ROUTE_REASON,
    NO_PROFILE_DNS_REASON,
    default_route_available,
    profile_hosts_resolvable,
    provider_skip_reason,
)
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def test_rmtree_and_fwalk_work_under_unshare_without_proc() -> None:
    reason = provider_skip_reason("unshare")
    if reason:
        pytest.skip(reason)
    if not default_route_available():
        pytest.skip(NO_DEFAULT_ROUTE_REASON)
    if not profile_hosts_resolvable():
        pytest.skip(NO_PROFILE_DNS_REASON)

    env = os.environ.copy()
    env.update({"OS_SANDBOX": "unshare", "UNSHARE_PROC": "none", "My_ENV": "1"})
    env.setdefault("TERM", "dumb")
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_rmtree_without_proc"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "TREE_REMOVED ['f.txt'] False" in result.stdout, result.stderr
