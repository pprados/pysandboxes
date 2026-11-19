# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Nested ``sandboxes()`` contexts share one daemon, which stops with the outermost one."""

import os
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox, sandbox, sandboxes
from pysandboxes.e import SandBoxError

config_path = Path(__file__).parent / "py-sandbox-test.profile"


@sandbox()
def echo(value: str) -> str:
    return value


@sandbox()
async def async_echo(value: str) -> str:
    return value


def test_an_inner_context_leaves_the_daemon_running_for_the_outer_one() -> None:
    with sandboxes(sandboxes_config=config_path):
        daemon = _os_sandbox._current_daemon
        assert daemon is not None
        with sandboxes(sandboxes_config=config_path):
            assert _os_sandbox._current_daemon is daemon
            assert echo("inner") == "inner"

        assert _os_sandbox._current_daemon is daemon
        assert echo("outer") == "outer"

    assert _os_sandbox._current_daemon is None


async def test_an_inner_async_context_leaves_the_daemon_running_for_the_outer_one() -> None:
    async with sandboxes(sandboxes_config=config_path):
        daemon = _os_sandbox._current_daemon
        assert daemon is not None
        async with sandboxes(sandboxes_config=config_path):
            assert _os_sandbox._current_daemon is daemon
            assert await async_echo("inner") == "inner"

        assert _os_sandbox._current_daemon is daemon
        assert await async_echo("outer") == "outer"

    assert _os_sandbox._current_daemon is None


def test_a_daemon_started_again_after_the_last_context_is_a_new_one() -> None:
    with sandboxes(sandboxes_config=config_path):
        first = _os_sandbox._current_daemon
    with sandboxes(sandboxes_config=config_path):
        second = _os_sandbox._current_daemon
        assert echo("again") == "again"

    assert first is not None and second is not None and second is not first


@pytest.mark.parametrize("change", ["provider", "rules", "environment", "result-mode"])
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_a_different_nested_policy_is_refused(change: str, asynchronous: bool) -> None:
    import asyncio

    kwargs: dict[str, Any] = {}
    if change == "provider":
        kwargs["os_sandbox"] = "none"
    elif change == "rules":
        kwargs["py_sandbox"] = "false"
    elif change == "environment":
        kwargs["envs"] = dict(os.environ, NESTED_POLICY="different")
    else:
        kwargs["remote_result_mode"] = "objects"

    async def check_async() -> None:
        async with sandboxes(sandboxes_config=config_path):
            daemon = _os_sandbox._current_daemon
            with pytest.raises(SandBoxError, match="different sandbox policy"):
                async with sandboxes(sandboxes_config=config_path, **kwargs):
                    pass
            assert _os_sandbox._current_daemon is daemon
            assert _os_sandbox._startup_counter == 1
            assert await async_echo("outer") == "outer"

    def check_sync() -> None:
        with sandboxes(sandboxes_config=config_path):
            daemon = _os_sandbox._current_daemon
            with pytest.raises(SandBoxError, match="different sandbox policy"):
                with sandboxes(sandboxes_config=config_path, **kwargs):
                    pass
            assert _os_sandbox._current_daemon is daemon
            assert _os_sandbox._startup_counter == 1
            assert echo("outer") == "outer"

    if asynchronous:
        await check_async()
    else:
        await asyncio.to_thread(check_sync)
    assert _os_sandbox._current_daemon is None
