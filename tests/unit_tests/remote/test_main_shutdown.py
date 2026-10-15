# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`daemon_shutdown`: what the daemon does, and in which order, when it is told to stop."""

import asyncio
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox, private_loop
from pysandboxes.remote import main_shutdown
from pysandboxes.remote.parameters import POLLING_DELAY


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []

    async def stop_daemon(**kwargs: Any) -> None:
        events.append(("stop", kwargs))

    async def shutdown_daemon(**kwargs: Any) -> None:
        events.append(("shutdown", kwargs))

    async def purge() -> None:
        events.append(("purge", None))

    monkeypatch.setattr(_os_sandbox, "async_stop_daemon", stop_daemon)
    monkeypatch.setattr(_os_sandbox, "async_shutdown_daemon", shutdown_daemon)
    monkeypatch.setattr(main_shutdown, "purge_loop", purge)
    monkeypatch.setattr(main_shutdown, "generate_config_from_learning", lambda: events.append(("generate", None)))
    monkeypatch.setattr(main_shutdown.time, "sleep", lambda delay: events.append(("sleep", delay)))
    monkeypatch.setattr(private_loop, "get_sandbox_loop", asyncio.get_running_loop)
    monkeypatch.setattr(main_shutdown, "is_learning_mode", lambda: False)
    return events


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_graceful_shutdown_stops_the_jobs_then_purges_then_shuts_down(journal: list[tuple[str, Any]]) -> None:
    await main_shutdown.daemon_shutdown(True)
    await _settle()

    assert journal == [
        ("stop", {"max_pending": 1}),
        ("sleep", POLLING_DELAY),
        ("purge", None),
        ("shutdown", {"graceful_shutdown": False}),
    ]


async def test_the_response_is_given_time_to_leave_before_the_purge(journal: list[tuple[str, Any]]) -> None:
    await main_shutdown.daemon_shutdown(True)

    assert journal == [("stop", {"max_pending": 1})]
    await _settle()
    assert [name for name, _ in journal] == ["stop", "sleep", "purge", "shutdown"]


async def test_a_shutdown_that_is_not_graceful_does_nothing_more(journal: list[tuple[str, Any]]) -> None:
    await main_shutdown.daemon_shutdown(False)
    await _settle()

    assert journal == []


@pytest.mark.parametrize("graceful", [True, False])
async def test_the_learned_rules_are_saved_first_in_learning_mode(
    journal: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch, graceful: bool
) -> None:
    monkeypatch.setattr(main_shutdown, "is_learning_mode", lambda: True)

    await main_shutdown.daemon_shutdown(graceful)
    await _settle()

    assert journal[0] == ("generate", None)
    assert [name for name, _ in journal].count("generate") == 1


async def test_the_rules_are_not_saved_outside_learning_mode(journal: list[tuple[str, Any]]) -> None:
    await main_shutdown.daemon_shutdown(True)
    await _settle()

    assert "generate" not in [name for name, _ in journal]
