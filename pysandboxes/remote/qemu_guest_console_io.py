# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Read QEMU ``-nographic`` serial streams without blocking on ``readline``.

Shared by ``python_sb`` (one-shot wait) and ``QemuSSEDaemon`` (background drain).
"""

import asyncio
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import TextIO

# QEMU console sentinels: guest prints these to stdout; host forwards only lines between them
PYTHON_OUTPUT_START = "[PYSANDBOXES]PYTHON_OUTPUT_START"
PYTHON_OUTPUT_END = "[PYSANDBOXES]PYTHON_OUTPUT_END"

# The guest program's stderr, in the 9p-shared run dir next to ``exitcode``. The console
# cannot carry it: QEMU multiplexes it onto the same host stream as stdout.
GUEST_STDERR_FILE = "stderr"

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
    guest_ready: asyncio.Event | None = None,
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
            if guest_ready is not None and PYTHON_OUTPUT_START.encode() in raw_line:
                guest_ready.set()
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


class GuestStderrTail:
    """Forward the guest's stderr file to the host's stderr while the VM is still running.

    The guest writes to a file in the 9p-shared run dir, and the host sees those writes
    as the guest makes them -- measured on a probe: a line written 13s into a 53s run
    reached the host at 13s, not at teardown. Reading the file only once the VM stopped
    would hold a long run's diagnostics back until the end, where a program run without
    a VM reports them as they happen.

    ``sys.stderr`` is line-buffered in the guest, so each line reaches the descriptor --
    and the share -- on its own.
    """

    def __init__(self, path: Path, *, out: TextIO | None = None, interval_s: float = 0.2) -> None:
        self._path = path
        self._out = out if out is not None else sys.stderr
        self._interval_s = interval_s
        self._offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _drain(self) -> None:
        """Copy whatever appeared since the last pass; a missing file just means nothing yet."""
        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = f.tell()
        except OSError:
            return
        if chunk:
            self._out.write(chunk)
            self._out.flush()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._drain()

    def __enter__(self) -> "GuestStderrTail":
        self._thread = threading.Thread(target=self._loop, name="qemu-guest-stderr", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        # What the guest flushed between the last pass and the halt, including the
        # traceback of a program that died: the run's most useful output is last.
        self._drain()


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


def prepare_qemu_guest_stdin() -> None:
    """Decode framed serial input into a pipe with ordinary byte and EOF semantics."""
    serial_fd = os.dup(0)
    read_fd, write_fd = os.pipe()
    os.dup2(read_fd, 0)
    os.close(read_fd)
    read, write, close = os.read, os.write, os.close

    def read_exact(size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = read(serial_fd, size - len(data))
            if not chunk:
                raise EOFError
            data.extend(chunk)
        return bytes(data)

    def relay() -> None:
        try:
            while size := int.from_bytes(read_exact(4), "big"):
                while size:
                    chunk = read_exact(min(size, _QEMU_CONSOLE_READ_CHUNK))
                    size -= len(chunk)
                    pending = memoryview(chunk)
                    while pending:
                        pending = pending[write(write_fd, pending) :]
        except (EOFError, OSError):
            pass
        finally:
            close(serial_fd)
            close(write_fd)

    threading.Thread(target=relay, name="qemu-guest-stdin", daemon=True).start()


async def _qemu_forward_stdin(writer: asyncio.StreamWriter, ready: asyncio.Event) -> None:
    """Hold host input until the guest is ready, then send length-prefixed data and EOF."""
    await ready.wait()
    loop = asyncio.get_running_loop()
    fd = sys.stdin.fileno()
    while True:
        readable: asyncio.Future[None] = loop.create_future()

        def wake(pending: asyncio.Future[None] = readable) -> None:
            if not pending.done():
                pending.set_result(None)

        try:
            loop.add_reader(fd, wake)
        except PermissionError:
            # Regular files and /dev/null are readable but cannot be registered with epoll.
            pass
        else:
            try:
                await readable
            finally:
                loop.remove_reader(fd)
        chunk = os.read(fd, _QEMU_CONSOLE_READ_CHUNK)
        writer.write(len(chunk).to_bytes(4, "big") + chunk)
        await writer.drain()
        if not chunk:
            return


async def qemu_wait_and_filter_console(
    process: asyncio.subprocess.Process,
    *,
    forward_all: bool = False,
    tee_file: TextIO | None = None,
    tee_lock: asyncio.Lock | None = None,
    mirror_logger: logging.Logger | None = None,
    forward_stdin: bool = False,
) -> int:
    """Wait for QEMU process and forward console output (all if forward_all, else between sentinels)."""
    if tee_file is not None and tee_lock is None:
        tee_lock = asyncio.Lock()
    state: list[int] = [_FORWARD_STATE_WAITING]
    guest_ready = asyncio.Event()
    t_stdout = asyncio.create_task(
        _qemu_read_and_forward(
            process.stdout,
            False,
            state,
            forward_all=forward_all,
            tee_file=tee_file,
            tee_lock=tee_lock,
            mirror_logger=mirror_logger,
            guest_ready=guest_ready,
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
    stdin_task = None
    if forward_stdin:
        assert process.stdin is not None

        async def forward_input() -> None:
            assert process.stdin is not None
            try:
                await _qemu_forward_stdin(process.stdin, guest_ready)
            except Exception:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                raise

        stdin_task = asyncio.create_task(forward_input())
    try:
        _, _, exit_code = await asyncio.gather(t_stdout, t_stderr, process.wait())
    finally:
        if stdin_task is not None:
            stdin_task.cancel()
            result = (await asyncio.gather(stdin_task, return_exceptions=True))[0]
            if isinstance(result, Exception):
                raise result
    return exit_code if exit_code is not None else -1
