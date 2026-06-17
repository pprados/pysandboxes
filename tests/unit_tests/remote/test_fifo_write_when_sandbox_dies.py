# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A sandbox that dies before reading its config must not hang the caller on the FIFO.

``open(fifo, "wb")`` blocks until a reader shows up. When the sandbox process never
starts -- bwrap rejecting an option, a missing binary -- no reader ever comes and the
caller waits forever instead of reporting the exit code.
"""

import asyncio
import os
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import SandBoxError
from pysandboxes.remote.client_subprocess_sse_daemon import _open_fifo_for_write


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
async def test_live_reader_yields_a_writable_descriptor(tmp_path: Path) -> None:
    """With a reader on the other end, the FIFO opens and stays usable for a blocking write."""
    pipe_path = tmp_path / "config.fifo"
    os.mkfifo(pipe_path)
    payload = b"x" * (1024 * 256)  # larger than the pipe buffer: the write must block, not fail
    process = await asyncio.create_subprocess_exec("/bin/cat", str(pipe_path), stdout=asyncio.subprocess.DEVNULL)

    fd = await asyncio.wait_for(_open_fifo_for_write(pipe_path, process), timeout=10)
    with os.fdopen(fd, "wb") as fifo:
        fifo.write(payload)
        fifo.flush()

    await asyncio.wait_for(process.wait(), timeout=10)
