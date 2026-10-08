# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The library never ends the application that uses it: a failure is an exception the application can handle."""

import asyncio
import os
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

import pysandboxes.private_loop as private_loop
from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.remote import bwrap_sse_daemon, firejail_sse_daemon, unshare_sse_daemon


class _Exited(Exception):
    """Raised by the patched exit functions, so an exit shows up as a test failure."""


@pytest.fixture
def no_exit(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    exits: list[object] = []

    def _exit(code: object = None) -> None:
        exits.append(code)
        raise _Exited(code)

    monkeypatch.setattr(os, "_exit", _exit)
    monkeypatch.setattr("sys.exit", _exit)
    return exits


def test_a_system_exit_in_a_loop_task_keeps_the_loop_and_the_process(
    monkeypatch: pytest.MonkeyPatch, no_exit: list[object]
) -> None:
    monkeypatch.setattr(private_loop, "_background_loop_ref", None)
    loop = private_loop._ensure_background_loop(new_loop=True)
    assert loop is not None
    try:

        async def leave() -> None:
            raise SystemExit(3)

        async def answer() -> int:
            return 42

        with pytest.raises(SystemExit):
            asyncio.run_coroutine_threadsafe(leave(), loop).result(timeout=5)
        assert asyncio.run_coroutine_threadsafe(answer(), loop).result(timeout=5) == 42
        assert no_exit == []
    finally:
        loop.call_soon_threadsafe(loop.stop)
        asyncio.set_event_loop(None)


def _bwrap_args(module: Any) -> None:
    module.BWrapSSEDaemon._bwrap_args(MagicMock(), EmptyRules, {}, Path("pipe"), Path("tmp"))


def _bwrap_network(module: Any) -> None:
    module.BWrapSSEDaemon._filtered_network(MagicMock(), EmptyRules, MagicMock(port=1), Path("pipe"))


def _firejail_args(module: Any) -> None:
    module.FireJailSSEDaemon._firejail_args(MagicMock(), EmptyRules, {}, Path("pipe"), Path("tmp"))


def _unshare_config(module: Any) -> None:
    module.UnshareSSEDaemon._prepare_unshare_config(MagicMock(), EmptyRules, Path("pipe"), "chroot")


@pytest.mark.parametrize(
    "module, call",
    [
        (bwrap_sse_daemon, _bwrap_args),
        (bwrap_sse_daemon, _bwrap_network),
        (firejail_sse_daemon, _firejail_args),
        (unshare_sse_daemon, _unshare_config),
    ],
    ids=["bwrap", "bwrap-network", "firejail", "unshare"],
)
def test_a_missing_binary_is_a_sandbox_error(
    monkeypatch: pytest.MonkeyPatch, no_exit: list[object], module: Any, call: Callable[[Any], None]
) -> None:
    monkeypatch.setattr(module, "which_command", lambda name: None)

    with pytest.raises(SandBoxError, match="not found"):
        call(module)
    assert no_exit == []
