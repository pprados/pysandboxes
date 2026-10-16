# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Nested ``sandboxes()`` contexts share one daemon, which stops with the outermost one."""

from pathlib import Path

from pysandboxes import _os_sandbox, sandbox, sandboxes

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
