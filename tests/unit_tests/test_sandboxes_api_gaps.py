# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Behaviour of `@sandbox` and `sandboxes` that the other API tests leave unobserved."""

import asyncio
import os
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pysandboxes.base_daemon import FakeDaemon
from pysandboxes.sandboxes_api import sandbox, sandboxes


def test_sync_decorated_function_keeps_its_identity() -> None:
    @sandbox
    def documented() -> None:
        """Its own doc."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Its own doc."


def test_async_decorated_function_keeps_its_identity() -> None:
    @sandbox
    async def documented() -> None:
        """Its own doc."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Its own doc."


def test_environment_defaults_to_the_process_one_and_a_given_mapping_is_kept() -> None:
    given = {"A": "1"}

    assert sandboxes().envs is os.environ
    assert sandboxes(envs=given).envs is given


def test_stopping_without_a_daemon_succeeds() -> None:
    assert asyncio.run(sandboxes()._stop_daemon()) is True


def test_stopping_a_started_daemon_shuts_it_down_and_succeeds() -> None:
    manager = sandboxes()
    manager._daemon = Mock(is_started=True)
    shutdown = AsyncMock()

    with patch("pysandboxes.sandboxes_api.async_shutdown_daemon", shutdown):
        assert asyncio.run(manager._stop_daemon()) is True

    shutdown.assert_awaited_once()
    assert manager._daemon is None


def test_stopping_a_daemon_that_is_being_restarted_still_shuts_it_down() -> None:
    """A restart clears is_started until the new sandbox is ready, and a call may be answered before that."""
    manager = sandboxes()
    manager._daemon = Mock(is_started=False)
    shutdown = AsyncMock()

    with patch("pysandboxes.sandboxes_api.async_shutdown_daemon", shutdown):
        assert asyncio.run(manager._stop_daemon()) is True

    shutdown.assert_awaited_once()
    assert manager._daemon is None


def test_signal_handlers_are_restored_from_the_main_thread() -> None:
    manager = sandboxes()
    manager._signals = {signal.SIGTERM: signal.SIG_DFL}

    with patch("pysandboxes.sandboxes_api.signal.signal") as install:
        manager._unregister_signals_handlers()

    install.assert_called_once_with(signal.SIGTERM, signal.SIG_DFL)
    assert manager._signals == {}


def test_signal_handlers_are_left_alone_from_a_worker_thread() -> None:
    manager = sandboxes()
    manager._signals = {signal.SIGTERM: signal.SIG_DFL}
    install = Mock()

    def run() -> None:
        with patch("pysandboxes.sandboxes_api.signal.signal", install):
            manager._unregister_signals_handlers()

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()

    install.assert_not_called()
    assert manager._signals == {}


def test_registering_from_a_worker_thread_installs_nothing() -> None:
    manager = sandboxes()
    install = Mock()

    def run() -> None:
        with patch("pysandboxes.sandboxes_api.signal.signal", install):
            manager._register_signals_handlers()

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()

    install.assert_not_called()
    assert manager._signals == {}


@contextmanager
def _installed_handler(previous: Any) -> Iterator[tuple[sandboxes, Callable[[int, Any], Any], Mock]]:
    """Register the handlers over a SIGTERM that held `previous`, and give the one installed for SIGTERM."""
    manager = sandboxes()
    install = Mock()
    with patch("pysandboxes.sandboxes_api.signal.getsignal", return_value=previous):
        with patch("pysandboxes.sandboxes_api.signal.signal", install):
            manager._register_signals_handlers()
            handler = next(c.args[1] for c in install.call_args_list if c.args[0] == signal.SIGTERM)
            yield manager, handler, install


def test_a_signal_nobody_registered_is_left_to_its_own_handler() -> None:
    with _installed_handler(signal.SIG_DFL) as (manager, handler, _):
        manager._signals.clear()

        assert handler(signal.SIGTERM, None) is not None


def test_a_signal_calls_the_previous_python_handler_from_the_main_thread() -> None:
    previous = Mock(return_value="previous answer")
    with _installed_handler(previous) as (_, handler, install):
        assert handler(signal.SIGTERM, None) == "previous answer"

    previous.assert_called_once_with(signal.SIGTERM, None)
    install.assert_called_with(signal.SIGTERM, previous)


def test_a_signal_caught_off_the_main_thread_interrupts_the_main_one() -> None:
    previous = Mock()
    with _installed_handler(previous) as (_, handler, _install):
        with patch("_thread.interrupt_main") as interrupt:
            worker = threading.Thread(target=handler, args=(signal.SIGTERM, None))
            worker.start()
            worker.join()

    interrupt.assert_called_once_with(signal.SIGTERM)
    previous.assert_not_called()


@pytest.mark.parametrize("in_sandbox", [False, True])
def test_a_default_disposition_stops_the_daemon_outside_the_sandbox_then_raises_the_signal(in_sandbox: bool) -> None:
    with _installed_handler(signal.SIG_DFL) as (manager, handler, _):
        with (
            patch("pysandboxes.sandboxes_api.is_in_sandbox", return_value=in_sandbox),
            patch("pysandboxes.sandboxes_api.get_sandbox_loop") as get_loop,
            patch("pysandboxes.sandboxes_api.asyncio.run_coroutine_threadsafe") as run_threadsafe,
            patch.object(sandboxes, "_stop_daemon", Mock()),
            patch("pysandboxes.sandboxes_api.signal.raise_signal") as raise_signal,
        ):
            assert handler(signal.SIGTERM, None) is None

    assert run_threadsafe.called is (not in_sandbox)
    assert get_loop.called is (not in_sandbox)
    raise_signal.assert_called_once_with(signal.SIGTERM)


def test_an_ignored_signal_stays_ignored() -> None:
    with _installed_handler(signal.SIG_IGN) as (_, handler, _install):
        with patch("pysandboxes.sandboxes_api.signal.raise_signal") as raise_signal:
            assert handler(signal.SIGTERM, None) is None

    raise_signal.assert_not_called()


def test_inside_a_sandbox_the_synchronous_manager_starts_nothing_and_stops_nothing() -> None:
    with patch("pysandboxes.sandboxes_api.is_in_sandbox", return_value=True):
        with patch("pysandboxes.sandboxes_api.asyncio.run_coroutine_threadsafe") as run_threadsafe:
            with sandboxes() as daemon:
                assert isinstance(daemon, FakeDaemon)

    run_threadsafe.assert_not_called()


def test_inside_a_sandbox_the_asynchronous_manager_starts_nothing_and_stops_nothing() -> None:
    async def scenario() -> None:
        manager = sandboxes()
        with patch("pysandboxes.sandboxes_api.is_in_sandbox", return_value=True):
            with patch.object(sandboxes, "_stop_daemon", AsyncMock()) as stop:
                async with manager as daemon:
                    assert isinstance(daemon, FakeDaemon)
                stop.assert_not_called()

    asyncio.run(scenario())
