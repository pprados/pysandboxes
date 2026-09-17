# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A daemon that fails to start must not leave its process running.

A failed start drops the provider, but not what it launched. With a subprocess that goes
mostly unnoticed; with QEMU it is a whole VM, and one was found still running long after
the run that started it had reported the failure and exited, competing for the CPU of
everything that came next.

Two paths reach the purge: the start itself raising, and the caller giving up on its own
clock while the start task carries on -- that second one is how the VM escaped, so the
timeout branch calls it too.
"""

from typing import Any

import pytest

from pysandboxes._os_sandbox import _kill_unstarted_sandbox


class _FakeProcess:
    """Enough of ``asyncio.subprocess.Process`` for the purge: a state and a kill()."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self.killed = False

    def kill(self) -> None:
        self.killed = True


class _FakeProvider:
    def __init__(self, process: Any) -> None:
        self._process = process


def test_a_daemon_that_never_started_loses_its_process() -> None:
    """The leak this fixes: with QEMU the survivor is a VM, and it outlived its run."""
    process = _FakeProcess(returncode=None)
    _kill_unstarted_sandbox(_FakeProvider(process))  # type: ignore[arg-type]
    assert process.killed


def test_a_process_that_already_exited_is_left_alone() -> None:
    process = _FakeProcess(returncode=1)
    _kill_unstarted_sandbox(_FakeProvider(process))  # type: ignore[arg-type]
    assert not process.killed


@pytest.mark.parametrize("provider", [None, _FakeProvider(None)])
def test_nothing_to_kill_is_not_an_error(provider: Any) -> None:
    """A start can fail before anything was launched; the purge runs on that path too."""
    _kill_unstarted_sandbox(provider)


def test_a_process_that_refuses_to_die_does_not_mask_the_start_failure() -> None:
    """The caller must still see why the daemon failed, not how the cleanup went."""

    class _Stubborn(_FakeProcess):
        def kill(self) -> None:
            raise ProcessLookupError("already gone")

    _kill_unstarted_sandbox(_FakeProvider(_Stubborn(returncode=None)))  # type: ignore[arg-type]
