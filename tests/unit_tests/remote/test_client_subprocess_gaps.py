# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Log format helpers, FIFO opening and daemon life cycle of the subprocess client."""

import asyncio
import errno
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.remote import client_subprocess_sse_daemon as client
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon


@pytest.fixture
def root_handlers(monkeypatch: pytest.MonkeyPatch) -> list[logging.Handler]:
    handlers: list[logging.Handler] = []
    monkeypatch.setattr(logging.getLogger(), "handlers", handlers)
    return handlers


class TestLogFormat:
    def test_the_format_of_the_first_handler_is_used(self, root_handlers: list[logging.Handler]) -> None:
        first = logging.StreamHandler()
        first.setFormatter(logging.Formatter("%(levelname)s|%(message)s"))
        root_handlers[:] = [first]

        assert client.get_log_formatter() == "%(levelname)s|%(message)s"

    def test_only_the_first_handler_counts(self, root_handlers: list[logging.Handler]) -> None:
        second = logging.StreamHandler()
        second.setFormatter(logging.Formatter("%(name)s|%(message)s"))
        root_handlers[:] = [logging.StreamHandler(), second]

        assert client.get_log_formatter() == "%(message)s"

    def test_without_a_handler_the_message_alone_is_logged(self, root_handlers: list[logging.Handler]) -> None:
        root_handlers.clear()

        assert client.get_log_formatter() == "%(message)s"


class TestOpenFifoForWrite:
    def test_an_error_other_than_no_reader_is_raised_at_once(self, tmp_path: Path) -> None:
        process = Mock(returncode=None)

        with pytest.raises(FileNotFoundError):
            asyncio.run(asyncio.wait_for(client._open_fifo_for_write(tmp_path / "absent", process), 2))

    def test_a_sandbox_that_exited_is_reported_with_its_code(self, tmp_path: Path) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        process = Mock(returncode=7)

        with pytest.raises(SandBoxError, match="exited with code 7"):
            asyncio.run(asyncio.wait_for(client._open_fifo_for_write(fifo, process), 2))

    def test_a_sandbox_that_never_reads_ends_with_a_timeout_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        monkeypatch.setattr(client, "TIMEOUT_FOR_START_DAEMON", 0.05)
        monkeypatch.setattr(client, "POLLING_DELAY", 0.01)

        with pytest.raises(SandBoxError, match="did not read its configuration"):
            asyncio.run(asyncio.wait_for(client._open_fifo_for_write(fifo, Mock(returncode=None)), 2))

    def test_a_reader_arriving_late_is_waited_for(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        monkeypatch.setattr(client, "POLLING_DELAY", 0.01)

        async def scenario() -> int:
            async def late_reader() -> int:
                await asyncio.sleep(0.1)
                return os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)

            reader = asyncio.create_task(late_reader())
            fd = await asyncio.wait_for(client._open_fifo_for_write(fifo, Mock(returncode=None)), 5)
            os.close(fd)
            return await reader

        os.close(asyncio.run(scenario()))

    def test_a_refusal_to_open_is_raised_whatever_its_number(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*args: Any, **kwargs: Any) -> int:
            raise OSError(errno.EACCES, "denied")

        monkeypatch.setattr(os, "open", refuse)

        with pytest.raises(OSError, match="denied"):
            asyncio.run(asyncio.wait_for(client._open_fifo_for_write(tmp_path / "fifo", Mock(returncode=None)), 2))

    def test_a_reader_gets_a_blocking_descriptor(self, tmp_path: Path) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            fd = asyncio.run(client._open_fifo_for_write(fifo, Mock(returncode=None)))
            try:
                assert os.get_blocking(fd)
            finally:
                os.close(fd)
        finally:
            os.close(reader)

    def test_no_reader_is_the_enxio_error(self, tmp_path: Path) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)

        with pytest.raises(OSError) as caught:
            os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)

        assert caught.value.errno == errno.ENXIO


class TestDaemonLifeCycle:
    def test_a_new_daemon_is_stopped_and_keeps_its_python_arguments(self) -> None:
        assert SubProcessDaemon("tok", python_args=["-X", "dev"])._python_args == ["-X", "dev"]
        daemon = SubProcessDaemon("tok")

        assert daemon._python_args == []
        assert daemon.is_started is False
        assert daemon.restart == 0

    @pytest.mark.parametrize(("configured", "expected"), [(-1, 6100), (4321, 4321)])
    def test_start_takes_a_free_port_only_when_none_is_configured(
        self, monkeypatch: pytest.MonkeyPatch, configured: int, expected: int
    ) -> None:
        monkeypatch.setattr(client, "find_free_port", lambda: 6100)
        daemon = SubProcessDaemon("tok")

        async def scenario() -> None:
            with (
                patch.object(SubProcessDaemon, "_re_start", AsyncMock()),
                patch.object(SubProcessDaemon, "watchdog", AsyncMock()),
            ):
                await daemon._start(EmptyRules._replace(port=configured), envs={}, log_level=logging.INFO, init_fn=None)
            await daemon._cancel_watchdog()

        asyncio.run(scenario())

        assert daemon.port == expected

    def test_cancelling_the_watchdog_forgets_it(self) -> None:
        daemon = SubProcessDaemon("tok")

        async def scenario() -> None:
            daemon._watchdog = asyncio.create_task(asyncio.Event().wait())
            await asyncio.sleep(0)
            await daemon._cancel_watchdog()

        asyncio.run(scenario())

        assert daemon._watchdog is None

    @pytest.mark.parametrize("graceful", [True, False])
    def test_shutdown_waits_for_a_graceful_exit_and_kills_otherwise(self, graceful: bool) -> None:
        daemon = SubProcessDaemon("tok")
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)
        daemon._process = process
        daemon._is_started = True
        daemon._accept_incoming = True

        async def scenario() -> None:
            with patch.object(SubProcessDaemon, "async_call_in_sandbox", AsyncMock()):
                await daemon._shutdown(graceful)

        asyncio.run(scenario())

        assert process.wait.await_count == (1 if graceful else 0)
        assert process.kill.called is (not graceful)
        assert daemon._process is None
        assert daemon.is_started is False
        assert daemon._accept_incoming is False


class _Dead:
    def __init__(self) -> None:
        self.returncode = 3

    async def wait(self) -> int:
        return 3


class TestWatchdogAttempts:
    def _daemon(self, **kwargs: Any) -> SubProcessDaemon:
        daemon = SubProcessDaemon("tok", base_delay=0.0, max_delay=0.0, **kwargs)
        daemon._process = _Dead()  # type: ignore[assignment]
        daemon._accept_incoming = True
        daemon._is_started = True
        return daemon

    def _run(self, daemon: SubProcessDaemon, stop_after: int) -> int:
        restarts = 0

        async def restart(*args: Any, **kwargs: Any) -> None:
            nonlocal restarts
            restarts += 1
            daemon._process = _Dead()  # type: ignore[assignment]
            if restarts >= stop_after:
                daemon._accept_incoming = False

        async def scenario() -> None:
            with patch.object(SubProcessDaemon, "_re_start", AsyncMock(side_effect=restart)):
                await daemon.watchdog(None, envs={}, log_level=0, init_fn=None)  # type: ignore[arg-type]

        asyncio.run(asyncio.wait_for(scenario(), 5))
        return restarts

    def test_giving_up_marks_the_daemon_as_stopped(self) -> None:
        daemon = self._daemon(max_attempts=2)

        self._run(daemon, stop_after=99)

        assert daemon.is_started is False
        assert daemon._failure

    def test_the_attempt_counter_restarts_after_the_reset_delay(self) -> None:
        daemon = self._daemon(max_attempts=2, reset_delay=-1.0)

        assert self._run(daemon, stop_after=6) == 6
        assert not daemon._failure
