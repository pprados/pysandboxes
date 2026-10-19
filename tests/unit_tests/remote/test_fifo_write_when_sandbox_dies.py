# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A sandbox that dies before reading its config must not hang the caller on the FIFO.

``open(fifo, "wb")`` blocks until a reader shows up. When the sandbox process never
starts -- bwrap rejecting an option, a missing binary -- no reader ever comes and the
caller waits forever instead of reporting the exit code.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import SandBoxError
from pysandboxes.remote.client_subprocess_sse_daemon import _open_fifo_for_write

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows has no os.mkfifo")


@pytest.mark.asyncio
async def test_dead_sandbox_reports_its_exit_code(tmp_path: Path) -> None:
    """No reader will ever come, so the write must fail with the exit code, not block."""
    pipe_path = tmp_path / "config.fifo"
    os.mkfifo(pipe_path)
    process = await asyncio.create_subprocess_exec("/bin/false")
    await process.wait()

    with pytest.raises(SandBoxError, match="exited with code 1"):
        await asyncio.wait_for(_open_fifo_for_write(pipe_path, process), timeout=10)


@pytest.mark.asyncio
async def test_a_sandbox_that_never_reads_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Alive but never reading: the wait must end on the start timeout, not last forever."""
    pipe_path = tmp_path / "config.fifo"
    os.mkfifo(pipe_path)
    monkeypatch.setattr("pysandboxes.remote.client_subprocess_sse_daemon.TIMEOUT_FOR_START_DAEMON", 0.2)
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
    try:
        with pytest.raises(SandBoxError, match="did not read its configuration"):
            await asyncio.wait_for(_open_fifo_for_write(pipe_path, process), timeout=5)
    finally:
        process.kill()
        await process.wait()
