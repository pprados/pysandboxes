# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A firejail that dies before reading its configuration is launched again.

firejail checks that the address it picked on the bridge is free with an ARP probe, and that probe fails now and
then (``arp.c: arp_check: Invalid argument``) when other traffic crosses the bridge. firejail exits with code 1
before the sandbox ever starts; a second launch picks another address.
"""

import asyncio
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import SandBoxError
from pysandboxes.remote.client_subprocess_sse_daemon import launch_sandbox
from pysandboxes.sb_types import Envs

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows has no os.mkfifo")

# Fails `FAILURES` times, counted in a file next to the script, then reads the configuration like the sandbox does.
SCRIPT = """#!/bin/sh
count=$(cat "$0.count" 2>/dev/null || echo 0)
echo $((count + 1)) > "$0.count"
if [ "$count" -lt "$FAILURES" ]; then exit 1; fi
cat "$1" > "$0.config"
"""


def _program(tmp_path: Path, name: str) -> Path:
    program = tmp_path / name
    program.write_text(SCRIPT)
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    return program


def _launch(program: Path, pipe_path: Path, failures: int, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FAILURES", str(failures))

    async def scenario() -> Any:
        process = await launch_sandbox(
            [str(program), str(pipe_path)], pipe_path=pipe_path, envs=Envs(dict(os.environ)), process_config="config"
        )
        await process.wait()
        return process

    return asyncio.run(asyncio.wait_for(scenario(), 30))


def _starts(program: Path) -> int:
    return int(Path(f"{program}.count").read_text())


def test_a_firejail_that_exits_before_reading_is_launched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _program(tmp_path, "firejail")

    process = _launch(program, tmp_path / "config.fifo", failures=2, monkeypatch=monkeypatch)

    assert process.returncode == 0
    assert _starts(program) == 3
    assert Path(f"{program}.config").exists()


def test_a_firejail_that_keeps_failing_ends_with_the_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program = _program(tmp_path, "firejail")

    with pytest.raises(SandBoxError, match="exited with code 1"):
        _launch(program, tmp_path / "config.fifo", failures=99, monkeypatch=monkeypatch)

    assert _starts(program) == 3


def test_another_sandbox_that_exits_before_reading_is_not_launched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _program(tmp_path, "bwrap")

    with pytest.raises(SandBoxError, match="exited with code 1"):
        _launch(program, tmp_path / "config.fifo", failures=1, monkeypatch=monkeypatch)

    assert _starts(program) == 1
