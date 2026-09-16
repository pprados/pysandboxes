# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The QEMU guest sends its stderr through the shared run dir, not the console.

QEMU multiplexes the guest console onto one host stream, so a program run in the VM
used to come back with its stdout and its stderr merged, where the same program run
without a VM keeps them apart. The run directory is already shared over 9p, and these
tests pin the two halves of that channel: the redirect catches what the program writes
to file descriptor 2, and the restore hands the console back.

The redirect is deliberately tested at the descriptor level rather than through
``sys.stderr``: a child process, or a C extension writing to fd 2 directly, has to land
in the same file as a ``print()``, and only ``os.dup2`` gives that.
"""

import io
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from pysandboxes.remote.main_sandbox import _redirect_guest_stderr, _restore_guest_stderr
from pysandboxes.remote.qemu_guest_console_io import _QEMU_CONSOLE_PREFIX, GuestStderrTail


@pytest.fixture
def restore_fd2() -> Iterator[None]:
    """Give fd 2 back whatever the test did to it, so a failure cannot blind pytest."""
    saved = os.dup(2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def test_the_redirect_captures_what_the_program_writes(tmp_path: Path, restore_fd2: None) -> None:
    saved_fd = _redirect_guest_stderr(str(tmp_path))
    try:
        # A text layer over fd 2, not ``sys.stderr``: pytest replaces that one with a
        # capture object that never reaches the descriptor, so asserting on it here
        # would test pytest. In the guest, ``sys.stderr`` is exactly this wrapper.
        with os.fdopen(os.dup(2), "w") as stderr_on_fd2:
            print("from-print", file=stderr_on_fd2, flush=True)
        os.write(2, b"from-fd\n")
    finally:
        _restore_guest_stderr(saved_fd)

    assert (tmp_path / "stderr").read_text() == "from-print\nfrom-fd\n"


def test_the_restore_hands_the_console_back(tmp_path: Path, restore_fd2: None) -> None:
    before = os.fstat(2)
    saved_fd = _redirect_guest_stderr(str(tmp_path))
    assert os.fstat(2).st_ino != before.st_ino, "the redirect did not take"

    _restore_guest_stderr(saved_fd)
    after = os.fstat(2)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_the_saved_descriptor_is_released(tmp_path: Path, restore_fd2: None) -> None:
    """A guest that ran a program per call would otherwise leak one descriptor each time."""
    saved_fd = _redirect_guest_stderr(str(tmp_path))
    assert saved_fd is not None
    _restore_guest_stderr(saved_fd)

    with pytest.raises(OSError):
        os.fstat(saved_fd)


def test_no_run_dir_leaves_stderr_alone(restore_fd2: None) -> None:
    """Outside a VM there is no shared dir; the console stays the caller's stderr."""
    before = os.fstat(2)
    assert _redirect_guest_stderr(None) is None
    after = os.fstat(2)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_an_unreachable_run_dir_leaves_stderr_alone(tmp_path: Path, restore_fd2: None) -> None:
    """The channel is a convenience: failing to open it must not silence the program."""
    before = os.fstat(2)
    assert _redirect_guest_stderr(str(tmp_path / "absent")) is None
    after = os.fstat(2)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_restoring_nothing_is_a_no_op(restore_fd2: None) -> None:
    before = os.fstat(2)
    _restore_guest_stderr(None)
    after = os.fstat(2)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_the_tail_forwards_before_the_vm_stops(tmp_path: Path) -> None:
    """The point of the tail: a line written mid-run reaches the caller mid-run.

    Reading the file only once the VM stopped would hold a long run's diagnostics back
    until the end, where the same program without a VM reports them as they happen.
    """
    out = io.StringIO()
    path = tmp_path / "stderr"

    with GuestStderrTail(path, out=out, interval_s=0.01):
        path.write_text("EARLY\n")
        deadline = time.monotonic() + 5.0
        while "EARLY" not in out.getvalue() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "EARLY" in out.getvalue(), "the tail waited for the run to end"
        path.write_text("EARLY\nLATE\n")

    # Leaving the block drains what the guest flushed after the last pass, which is
    # where the traceback of a program that died sits.
    assert out.getvalue() == "EARLY\nLATE\n"


def test_the_tail_survives_a_run_that_wrote_nothing(tmp_path: Path) -> None:
    """A program with a silent stderr never creates the file; that is not an error."""
    out = io.StringIO()
    with GuestStderrTail(tmp_path / "absent", out=out, interval_s=0.01):
        time.sleep(0.05)
    assert out.getvalue() == ""


@pytest.mark.parametrize(
    "line,expected",
    [
        ("[   12.525772] cloud-init[672]: 42\n", "42\n"),
        ("[   12.525772] cloud-init[672]:42\n", "42\n"),
        ("[   12.525772] cloud-init[672]:  42\n", " 42\n"),
        ("42\n", "42\n"),
    ],
)
def test_the_console_prefix_takes_its_trailing_space(line: str, expected: str) -> None:
    """``print(42)`` must reach the caller as ``42``, not as `` 42``."""
    assert re.sub(_QEMU_CONSOLE_PREFIX, "", line) == expected
