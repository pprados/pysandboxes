# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Timeouts must finish cancellation and reap owned processes before returning."""

import asyncio
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from pysandboxes import _os_sandbox as lifecycle
from pysandboxes.e import SandBoxError, SandBoxProtocolError
from pysandboxes.private_loop import _reset_sandbox_loop, get_sandbox_loop
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    yield
    lifecycle._current_daemon = None
    lifecycle._starting_daemon = None
    lifecycle._active_fingerprint = None
    lifecycle._startup_counter = 0
    _reset_sandbox_loop()


@pytest.mark.parametrize("assigned", [False, True])
def test_start_timeout_reaps_process_and_finishes_cleanup(
    assigned: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    finished = threading.Event()
    processes: list[asyncio.subprocess.Process] = []

    class BlockedStart(SubProcessDaemon):
        async def _start(self, *args: Any, **kwargs: Any) -> None:
            process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")
            processes.append(process)
            if assigned:
                self._process = process
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                # Model an async launcher completing ownership transfer during cancellation.
                await asyncio.sleep(0.02)
                self._process = process
                finished.set()

    profile = tmp_path / "profile"
    profile.write_text("py-sandbox=true\nos-sandbox=subprocess\n")
    rules = load_and_parse_config(config_path=profile)
    monkeypatch.setattr(lifecycle, "providers_factory", {"subprocess": BlockedStart})
    monkeypatch.setattr(lifecycle, "TIMEOUT_FOR_START_DAEMON", 0.1)
    loop = get_sandbox_loop()
    try:
        with pytest.raises(RuntimeError, match="failed to start"):
            lifecycle.start_daemon(rules, envs={}, log_level=0)
        assert entered.is_set()
        assert finished.is_set()
        assert processes[0].returncode is not None
        assert lifecycle._current_daemon is None
        assert lifecycle._starting_daemon is None
        assert lifecycle._active_fingerprint is None
        assert lifecycle._startup_counter == 0
    finally:

        async def cleanup() -> None:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()

        asyncio.run_coroutine_threadsafe(cleanup(), loop).result(5)


def test_rpc_timeout_drains_client_and_terminates_daemon_before_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finished = threading.Event()
    cancelling = threading.Event()
    allow_cleanup = threading.Event()

    class BlockedRPC(SubProcessDaemon):
        async def async_call_in_sandbox(self, *args: Any, **kwargs: Any) -> Any:
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                await asyncio.to_thread(allow_cleanup.wait)
                finished.set()

    daemon = BlockedRPC("token")
    daemon._is_started = True
    daemon._accept_incoming = True
    loop = get_sandbox_loop()
    process = asyncio.run_coroutine_threadsafe(
        asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)"), loop
    ).result(5)
    daemon._process = process
    lifecycle._current_daemon = daemon
    lifecycle._startup_counter = 2
    profile = tmp_path / "profile"
    profile.write_text("py-sandbox=true\nos-sandbox=subprocess\n")
    rules = load_and_parse_config(config_path=profile)
    lifecycle._active_fingerprint = lifecycle._policy_fingerprint(rules, {}, 0, None, None)
    monkeypatch.setenv("PYSANDBOXES_RPC_TIMEOUT", "0.05")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            call = executor.submit(daemon.call_in_sandbox, lambda: None, False)
            try:
                assert cancelling.wait(5)
                with pytest.raises(SandBoxError):
                    lifecycle.start_daemon(rules, envs={}, log_level=0)
            finally:
                allow_cleanup.set()
            with pytest.raises(SandBoxProtocolError, match="did not respond"):
                call.result(5)
        assert finished.is_set()
        assert process.returncode is not None
        with pytest.raises(SandBoxProtocolError):
            daemon.call_in_sandbox(lambda: None, False)
        with pytest.raises(SandBoxError):
            lifecycle.start_daemon(rules, envs={}, log_level=0)
        lifecycle.shutdown_daemon()
        lifecycle.shutdown_daemon()
        assert lifecycle._current_daemon is None
        assert lifecycle._active_fingerprint is None
        assert lifecycle._startup_counter == 0

        class Ready(SubProcessDaemon):
            async def _start(self, *args: Any, **kwargs: Any) -> None:
                self._is_started = True
                self._accept_incoming = True

        monkeypatch.setattr(lifecycle, "providers_factory", {"subprocess": Ready})
        restarted = lifecycle.start_daemon(rules, envs={}, log_level=0)
        assert restarted is not daemon
        assert lifecycle._startup_counter == 1
        asyncio.run_coroutine_threadsafe(lifecycle.async_shutdown_daemon(False), get_sandbox_loop()).result(5)
    finally:
        if process.returncode is None:
            process.kill()
            asyncio.run_coroutine_threadsafe(process.wait(), loop).result(5)
