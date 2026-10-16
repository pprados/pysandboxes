# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A sandbox killed by SIGKILL is started again by the watchdog, and nothing of the first one is left.

Each backend runs in its own process (``tst_recovery``): one that does not recover leaves its daemon half dead.
QEMU is left out: killing a guest is another scenario.
"""

import json
import os
import subprocess
import sys

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, os_sandbox_params, provider_skip_reason
from .test_guards_with_providers import ROOT_DIR

_ROWS = [row for row in os_sandbox_params() if not str(row.values[0]).startswith("qemu")]


@pytest.mark.skipif(sys.platform != "linux", reason="the sandbox processes are found through /proc")
@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_killed_sandbox_is_started_again_and_answers(os_sandbox: str) -> None:
    if reason := provider_skip_reason(os_sandbox):
        pytest.skip(reason)

    done = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_recovery"],
        cwd=ROOT_DIR,
        env={**os.environ, "OS_SANDBOX": backend_of(os_sandbox)},
        capture_output=True,
        text=True,
        timeout=300,
    )

    line = next((line for line in done.stdout.splitlines() if line.startswith("RESULT ")), None)
    assert line is not None, done.stdout + done.stderr
    result = json.loads(line.removeprefix("RESULT "))
    assert result.get("killed"), result
    assert result["answered"], result
    assert result["restarted"], result
    assert result["left"] == [], result
