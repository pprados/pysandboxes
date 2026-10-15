# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Behaviour of `@sandbox` and `sandboxes` that the other API tests leave unobserved."""

import asyncio
import os
import signal
import threading
from unittest.mock import AsyncMock, Mock, patch

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
