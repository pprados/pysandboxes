# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Behaviour of `@sandbox` and `sandboxes` that the other API tests leave unobserved."""

import asyncio
import logging
import os
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pysandboxes import _os_sandbox
from pysandboxes.base_daemon import FakeDaemon
from pysandboxes.e import SandBoxError
from pysandboxes.private_loop import _reset_sandbox_loop, get_sandbox_loop
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


def test_shutdown_failure_can_retry_without_reusing_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        daemon = FakeDaemon("token")
        daemon._is_started = True
        daemon._accept_incoming = True
        shutdown = AsyncMock(side_effect=[RuntimeError("failed"), None])
        monkeypatch.setattr(daemon, "_shutdown", shutdown)
        monkeypatch.setattr(_os_sandbox, "_current_daemon", daemon)
        monkeypatch.setattr(_os_sandbox, "_startup_counter", 1)
        monkeypatch.setattr(_os_sandbox, "_reset_sandbox_loop", lambda: None)
        manager = sandboxes()
        manager._daemon = daemon
        with pytest.raises(RuntimeError, match="failed"):
            await manager._stop_daemon()
        assert manager._daemon is daemon
        assert _os_sandbox._current_daemon is daemon
        assert _os_sandbox._active_fingerprint is None
        assert not daemon._accept_incoming
        with pytest.raises(SandBoxError, match="Cannot reuse an active daemon"):
            _os_sandbox._check_nested_policy(Mock())
        daemon._is_started = False
        await manager._stop_daemon()
        assert shutdown.await_count == 2
        assert manager._daemon is None

    asyncio.run(scenario())


def test_concurrent_shutdown_completes_on_owned_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = get_sandbox_loop()
    entered = threading.Event()
    release = asyncio.Event()
    daemon = FakeDaemon("token")
    daemon._is_started = True

    async def shutdown(graceful: bool) -> None:
        entered.set()
        await release.wait()
        daemon._is_started = False

    monkeypatch.setattr(daemon, "_shutdown", shutdown)
    monkeypatch.setattr(_os_sandbox, "_current_daemon", daemon)
    monkeypatch.setattr(_os_sandbox, "_startup_counter", 1)
    manager = sandboxes()
    manager._daemon = daemon
    try:
        first = asyncio.run_coroutine_threadsafe(manager._stop_daemon(), loop)
        assert entered.wait(2)
        second = asyncio.run_coroutine_threadsafe(manager._stop_daemon(), loop)
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(2)
        assert not second.done()
        loop.call_soon_threadsafe(release.set)
        assert first.result(2)
        assert second.result(2)
    finally:
        if loop.is_running():
            loop.call_soon_threadsafe(release.set)
        _reset_sandbox_loop()


def test_signal_handlers_are_restored_from_the_main_thread() -> None:
    manager = sandboxes()
    manager._signals = {signal.SIGTERM: signal.SIG_DFL}

    with patch("pysandboxes.sandboxes_api.signal.signal") as install:
        manager._unregister_signals_handlers()

    install.assert_called_once_with(signal.SIGTERM, signal.SIG_DFL)
    assert manager._signals == {}


def test_signal_handlers_are_preserved_when_exit_occurs_on_a_worker_thread() -> None:
    manager = sandboxes()
    manager._signals = {signal.SIGTERM: signal.SIG_DFL}
    install = Mock()
    errors: list[Exception] = []

    def run() -> None:
        with patch("pysandboxes.sandboxes_api.signal.signal", install):
            try:
                manager._unregister_signals_handlers()
            except RuntimeError as exc:
                errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()

    install.assert_not_called()
    assert len(errors) == 1
    assert manager._signals == {signal.SIGTERM: signal.SIG_DFL}


def test_worker_thread_exit_stops_daemon_despite_signal_affinity_error() -> None:
    manager = sandboxes()
    manager._signals = {signal.SIGTERM: signal.SIG_DFL}
    manager._daemon = Mock()
    errors: list[Exception] = []

    def exit_context() -> None:
        try:
            manager.__exit__(None, None, None)
        except RuntimeError as exc:
            errors.append(exc)

    with (
        patch("pysandboxes.sandboxes_api.get_sandbox_loop"),
        patch("pysandboxes.sandboxes_api.asyncio.run_coroutine_threadsafe") as run_threadsafe,
        patch.object(sandboxes, "_stop_daemon", Mock()),
    ):
        worker = threading.Thread(target=exit_context)
        worker.start()
        worker.join()
    assert len(errors) == 1
    run_threadsafe.assert_called_once()
    assert manager._signals == {signal.SIGTERM: signal.SIG_DFL}


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


def test_default_signal_is_raised_if_daemon_loop_lookup_fails() -> None:
    with _installed_handler(signal.SIG_DFL) as (manager, handler, _):
        manager._daemon = Mock()
        with (
            patch("pysandboxes.sandboxes_api.get_sandbox_loop", side_effect=RuntimeError("loop failed")),
            patch("pysandboxes.sandboxes_api.signal.raise_signal") as raise_signal,
            pytest.raises(RuntimeError, match="loop failed"),
        ):
            handler(signal.SIGTERM, None)
    raise_signal.assert_called_once_with(signal.SIGTERM)


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


@pytest.mark.parametrize("nested", [False, True])
def test_a_default_disposition_stops_the_daemon_outside_the_sandbox_then_raises_the_signal(nested: bool) -> None:
    """A nested entry (`manager._daemon` is the `FakeDaemon` `__enter__` sets for it) owns no real daemon to
    stop. `is_in_sandbox()` cannot tell the two cases apart here: the `none` provider's `_start` leaves it
    true for a non-nested entry too, so the daemon's own type is what the handler checks instead.
    """
    with _installed_handler(signal.SIG_DFL) as (manager, handler, _):
        manager._daemon = FakeDaemon(token="fake") if nested else Mock()
        with (
            patch("pysandboxes.sandboxes_api.get_sandbox_loop") as get_loop,
            patch("pysandboxes.sandboxes_api.asyncio.run_coroutine_threadsafe") as run_threadsafe,
            patch.object(sandboxes, "_stop_daemon", Mock()),
            patch("pysandboxes.sandboxes_api.signal.raise_signal") as raise_signal,
        ):
            assert handler(signal.SIGTERM, None) is None

    assert run_threadsafe.called is (not nested)
    assert get_loop.called is (not nested)
    raise_signal.assert_called_once_with(signal.SIGTERM)


def test_default_signal_is_raised_when_shutdown_fails() -> None:
    with _installed_handler(signal.SIG_DFL) as (manager, handler, _):
        manager._daemon = Mock()
        with (
            patch("pysandboxes.sandboxes_api.get_sandbox_loop"),
            patch("pysandboxes.sandboxes_api.asyncio.run_coroutine_threadsafe") as run_threadsafe,
            patch.object(sandboxes, "_stop_daemon", Mock()),
            patch("pysandboxes.sandboxes_api.signal.raise_signal") as raise_signal,
        ):
            run_threadsafe.return_value.result.side_effect = RuntimeError("shutdown failed")
            with pytest.raises(RuntimeError, match="shutdown failed"):
                handler(signal.SIGTERM, None)
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


@pytest.fixture
def restored_root_level() -> Iterator[int]:
    level = logging.root.level
    yield level
    logging.root.setLevel(level)


def test_the_log_level_variable_sets_the_root_level(monkeypatch: pytest.MonkeyPatch, restored_root_level: int) -> None:
    from pysandboxes.sandboxes_api import _apply_log_level_env

    monkeypatch.setenv("PYSANDBOXES_LOG_LEVEL", "error")

    _apply_log_level_env()

    assert logging.root.level == logging.ERROR


def test_without_the_log_level_variable_the_root_level_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, restored_root_level: int
) -> None:
    from pysandboxes.sandboxes_api import _apply_log_level_env

    monkeypatch.delenv("PYSANDBOXES_LOG_LEVEL", raising=False)
    logging.root.setLevel(logging.CRITICAL)

    _apply_log_level_env()

    assert logging.root.level == logging.CRITICAL
