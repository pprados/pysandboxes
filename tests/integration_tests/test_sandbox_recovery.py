# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A sandbox killed by SIGKILL is started again by the watchdog, and nothing of the first one is left.

Each backend runs in its own process (``tst_recovery``): one that does not recover leaves its daemon half dead.
QEMU is left out: killing a guest is another scenario.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, os_sandbox_params, provider_skip_reason
from .test_guards_with_providers import ROOT_DIR

_ROWS = [row for row in os_sandbox_params() if not str(row.values[0]).startswith("qemu")]


def _report_pipe_holders(child: "subprocess.Popen[str]", stdout_pipe: str) -> str:
    """Name and kill what keeps the stdout pipe of a finished child open: the verdict is printed, yet the read hangs."""
    holders = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in (os.getpid(), child.pid):
            continue
        try:
            if any(os.readlink(fd) == stdout_pipe for fd in (entry / "fd").iterdir()):
                stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                holders.append(f"pid={entry.name} ppid={stat[1]} state={stat[0]} cmd={cmdline[:200]}")
                os.kill(int(entry.name), signal.SIGKILL)
        except OSError:
            continue
    child.kill()
    out, err = child.communicate()
    return (
        f"tst_recovery returncode={child.returncode} did not release its stdout within 300s.\n"
        f"holders of {stdout_pipe}: {holders or 'none found'}\nstdout: {out}\nstderr: {err}"
    )


@pytest.mark.skipif(sys.platform != "linux", reason="the sandbox processes are found through /proc")
@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_killed_sandbox_is_started_again_and_answers(os_sandbox: str) -> None:
    if reason := provider_skip_reason(os_sandbox):
        pytest.skip(reason)

    child = subprocess.Popen(
        [sys.executable, "-m", "tests.integration_tests.tst_recovery"],
        cwd=ROOT_DIR,
        env={**os.environ, "OS_SANDBOX": backend_of(os_sandbox)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_pipe = os.readlink(f"/proc/{child.pid}/fd/1")
    try:
        out, err = child.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        pytest.fail(_report_pipe_holders(child, stdout_pipe))
    done = subprocess.CompletedProcess(child.args, child.returncode, out, err)

    line = next((line for line in done.stdout.splitlines() if line.startswith("RESULT ")), None)
    assert line is not None, done.stdout + done.stderr
    result = json.loads(line.removeprefix("RESULT "))
    assert result.get("killed"), result
    assert result["answered"], result
    assert result["restarted"], result
    assert result["left"] == [], result
