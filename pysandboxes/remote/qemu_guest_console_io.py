# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Read QEMU ``-nographic`` serial streams without blocking on ``readline``.

Shared by ``python_sb`` (one-shot wait) and ``QemuSSEDaemon`` (background drain).
"""

import asyncio
import logging
import re
import sys
import time
from pathlib import Path
from typing import TextIO

# QEMU console sentinels: guest prints these to stderr; host forwards only lines between them
PYTHON_OUTPUT_START = "[PYSANDBOXES]PYTHON_OUTPUT_START"
PYTHON_OUTPUT_END = "[PYSANDBOXES]PYTHON_OUTPUT_END"

# QEMU console filter state: 0=waiting for start sentinel, 1=forwarding, 2=stopped
_FORWARD_STATE_WAITING = 0
_FORWARD_STATE_FORWARDING = 1
_FORWARD_STATE_STOPPED = 2

# Strip kernel/cloud-init style prefix e.g. "[   12.525772] cloud-init[672]: "
# The trailing " ?" matters: without it every forwarded line keeps the space that
# separated the prefix from the text, and `print(42)` reaches the caller as " 42".
_QEMU_CONSOLE_PREFIX = re.compile(r"^\s*\[\s*\d+\.\d+\]\s*[\w-]+\[\d+\]: ?")

# readline() can block forever on QEMU -nographic if a line never ends with \n;
# read(max_chunk) returns as soon as any data or EOF arrives (no newline required).
_QEMU_CONSOLE_READ_CHUNK = 65536
_QEMU_CONSOLE_BUF_MAX = 1024 * 1024


def _qemu_console_text_for_terminal(text: str) -> str:
    """Normalize QEMU serial line endings to CRLF for correct terminal display."""
    if not text:
        return text
    if text.endswith("\n"):
        return text[:-1].rstrip("\r") + "\r\n"
    return text


def _qemu_forward_state_for_line(line: str, state: list[int]) -> bool:
    """Update state from line (start/end sentinels) and return True if line should be printed."""
    s = state[0]
    if s == _FORWARD_STATE_WAITING:
        if PYTHON_OUTPUT_START in line:
            state[0] = _FORWARD_STATE_FORWARDING
        return False
    if s == _FORWARD_STATE_FORWARDING:
        if PYTHON_OUTPUT_END in line:
            state[0] = _FORWARD_STATE_STOPPED
            return False
        return True
    return False


def _mirror_line(mirror_logger: logging.Logger | None, text: str) -> None:
    if mirror_logger is None:
        return
    line = text.rstrip("\r\n")
    if line:
        mirror_logger.debug("[qemu-serial] %s", line)


async def _qemu_emit_qemu_console_line(
    raw: bytes,
    out: TextIO,
    state: list[int],
    *,
    forward_all: bool,
    tee_file: TextIO | None,
    tee_lock: asyncio.Lock | None,
    mirror_logger: logging.Logger | None,
) -> None:
    """Decode one newline-terminated (or forced) chunk and apply sentinel filtering."""
    if not raw:
        return
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = str(raw)
    text_stripped = _QEMU_CONSOLE_PREFIX.sub("", text)
    if forward_all or _qemu_forward_state_for_line(text_stripped, state):
        print(
            _qemu_console_text_for_terminal(text_stripped),
            end="",
            file=out,
            flush=True,
        )
        _mirror_line(mirror_logger, text_stripped)
    if tee_file is not None:
        assert tee_lock is not None
        async with tee_lock:
            tee_file.write(text)
            tee_file.flush()


async def _qemu_read_and_forward(
    stream: asyncio.StreamReader | None,
    is_stderr: bool,
    state: list[int],
    *,
    forward_all: bool = False,
    tee_file: TextIO | None = None,
    tee_lock: asyncio.Lock | None = None,
    mirror_logger: logging.Logger | None = None,
) -> None:
    """Read QEMU console stream and forward lines (all if forward_all, else between sentinels)."""
    if stream is None:
        return
    out = sys.stderr if is_stderr else sys.stdout
    buf = bytearray()
    while True:
        try:
            chunk = await stream.read(_QEMU_CONSOLE_READ_CHUNK)
        except (ConnectionResetError, BrokenPipeError):
            break
        if not chunk:
            break
        buf.extend(chunk)
        while True:
            nl = buf.find(b"\n")
            cr = buf.find(b"\r") if forward_all else -1
            end_exclusive = -1
            if forward_all:
                if nl >= 0 and (cr < 0 or nl < cr):
                    end_exclusive = nl + 1
                elif cr >= 0:
                    end_exclusive = cr + 1
            elif nl >= 0:
                end_exclusive = nl + 1
            if end_exclusive < 0:
                if len(buf) >= _QEMU_CONSOLE_BUF_MAX:
                    line = bytes(buf)
                    buf.clear()
                    await _qemu_emit_qemu_console_line(
                        line,
                        out,
                        state,
                        forward_all=forward_all,
                        tee_file=tee_file,
                        tee_lock=tee_lock,
                        mirror_logger=mirror_logger,
                    )
                break
            raw_line = bytes(buf[:end_exclusive])
            del buf[:end_exclusive]
            await _qemu_emit_qemu_console_line(
                raw_line,
                out,
                state,
                forward_all=forward_all,
                tee_file=tee_file,
                tee_lock=tee_lock,
                mirror_logger=mirror_logger,
            )
    if buf:
        await _qemu_emit_qemu_console_line(
            bytes(buf),
            out,
            state,
            forward_all=forward_all,
            tee_file=tee_file,
            tee_lock=tee_lock,
            mirror_logger=mirror_logger,
        )


def start_qemu_serial_drain_tasks(
    process: asyncio.subprocess.Process,
    *,
    forward_all: bool,
    mirror_logger: logging.Logger | None = None,
    tee_file: TextIO | None = None,
) -> list[asyncio.Task[None]]:
    """Spawn tasks that drain QEMU stdout/stderr pipes (non-blocking for the guest).

    Use when ``qemu.show_boot_console=true`` so serial output is copied to the host
    terminal **and** optional ``mirror_logger`` (DEBUG), instead of relying on FD
    inheritance (broken under some ``podman run`` / pytest combinations).
    """
    tee_lock = asyncio.Lock() if tee_file is not None else None
    state: list[int] = [_FORWARD_STATE_WAITING]
    return [
        asyncio.create_task(
            _qemu_read_and_forward(
                process.stdout,
                False,
                state,
                forward_all=forward_all,
                tee_file=tee_file,
                tee_lock=tee_lock,
                mirror_logger=mirror_logger,
            ),
            name="qemu-serial-stdout",
        ),
        asyncio.create_task(
            _qemu_read_and_forward(
                process.stderr,
                True,
                state,
                forward_all=forward_all,
                tee_file=tee_file,
                tee_lock=tee_lock,
                mirror_logger=mirror_logger,
            ),
            name="qemu-serial-stderr",
        ),
    ]


def read_qemu_guest_exitcode(
    exitcode_file: Path,
    *,
    max_wait_s: float = 3.0,
    interval_s: float = 0.05,
) -> int | None:
    """Read guest-written exit code from the shared run dir, with short polling."""
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        if exitcode_file.exists():
            try:
                raw = exitcode_file.read_text().strip()
                return int(raw)
            except (ValueError, OSError):
                pass
        time.sleep(interval_s)
    return None


async def qemu_wait_and_filter_console(
    process: asyncio.subprocess.Process,
    *,
    forward_all: bool = False,
    tee_file: TextIO | None = None,
    tee_lock: asyncio.Lock | None = None,
    mirror_logger: logging.Logger | None = None,
) -> int:
    """Wait for QEMU process and forward console output (all if forward_all, else between sentinels)."""
    if tee_file is not None and tee_lock is None:
        tee_lock = asyncio.Lock()
    state: list[int] = [_FORWARD_STATE_WAITING]
    t_stdout = asyncio.create_task(
        _qemu_read_and_forward(
            process.stdout,
            False,
            state,
            forward_all=forward_all,
            tee_file=tee_file,
            tee_lock=tee_lock,
            mirror_logger=mirror_logger,
        )
    )
    t_stderr = asyncio.create_task(
        _qemu_read_and_forward(
            process.stderr,
            True,
            state,
            forward_all=forward_all,
            tee_file=tee_file,
            tee_lock=tee_lock,
            mirror_logger=mirror_logger,
        )
    )
    _, _, exit_code = await asyncio.gather(
        t_stdout,
        t_stderr,
        process.wait(),
    )
    return exit_code if exit_code is not None else -1
