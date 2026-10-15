# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`UnshareSSEDaemon._watchdog_loop`: restart policy, backoff and give-up of the unshare provider."""

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import unshare_sse_daemon as usd
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon


class _Process:
    """A sandbox process whose `wait` pops the next exit code, or raises when given an exception."""

    def __init__(self, *codes: Any) -> None:
        self.codes = list(codes)

    async def wait(self) -> Any:
        code = self.codes.pop(0)
        if isinstance(code, BaseException):
            raise code
        return code


class _Run:
    def __init__(self, daemon: UnshareSSEDaemon) -> None:
        self.daemon = daemon
        self.launches: list[tuple[Any, dict[str, Any]]] = []
        self.sleeps: list[float] = []
        self.draws: list[tuple[float, float]] = []

    async def launch(self, rules: Any, **kwargs: Any) -> None:
        self.launches.append((rules, kwargs))
        self.daemon._process = _Process(1)  # type: ignore[assignment]

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    def uniform(self, low: float, high: float) -> float:
        self.draws.append((low, high))
        return high

    def run(self, *, init_fn: Any = None) -> None:
        async def scenario() -> None:
            with (
                patch.object(UnshareSSEDaemon, "_launch", staticmethod(self.launch)),
                patch.object(usd.asyncio, "sleep", self.sleep),
                patch.object(usd.random, "uniform", self.uniform),
            ):
                await self.daemon._watchdog_loop(EmptyRules, envs={"A": "b"}, log_level=5, init_fn=init_fn)

        asyncio.run(asyncio.wait_for(scenario(), 5))


def _daemon(*codes: Any, accept: bool = True, **kwargs: Any) -> UnshareSSEDaemon:
    daemon = UnshareSSEDaemon("tok", **kwargs)
    daemon._process = _Process(*codes)  # type: ignore[assignment]
    daemon._accept_incoming = accept
    daemon._is_started = True
    return daemon


class TestWatchdogLoop:
    def test_without_a_process_nothing_happens(self) -> None:
        daemon = _daemon()
        daemon._process = None
        run = _Run(daemon)

        run.run()

        assert run.launches == [] and run.sleeps == []

    def test_an_exit_while_stopping_is_not_a_crash(self) -> None:
        daemon = _daemon(0, accept=False)
        run = _Run(daemon)

        run.run()

        assert run.launches == []
        assert daemon._failure is None
        assert daemon._attempts == 0

    @pytest.mark.parametrize("code", [0, 1, -9])
    def test_any_exit_while_accepting_restarts_the_sandbox(self, code: int) -> None:
        daemon = _daemon(code)
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            await _Run.launch(run, rules, **kwargs)
            daemon._accept_incoming = False
            daemon._process = _Process(0)  # type: ignore[assignment]

        run.launch = launch  # type: ignore[method-assign]
        run.run()

        assert len(run.launches) == 1

    def test_the_launch_receives_the_rules_the_environment_the_level_and_the_init_function(self) -> None:
        daemon = _daemon(1)
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            run.launches.append((rules, kwargs))
            daemon._accept_incoming = False
            daemon._process = _Process(0)  # type: ignore[assignment]

        run.launch = launch  # type: ignore[method-assign]
        run.run(init_fn=print)

        assert run.launches == [(EmptyRules, {"envs": {"A": "b"}, "log_level": 5, "init_fn": print})]

    def test_the_backoff_grows_by_the_factor_and_is_capped(self) -> None:
        daemon = _daemon(1, base_delay=1.0, factor=2.0, max_delay=3.0, max_attempts=10, reset_delay=1e9)
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            run.launches.append((rules, kwargs))
            daemon._process = _Process(1)  # type: ignore[assignment]
            if len(run.launches) == 4:
                daemon._accept_incoming = False

        run.launch = launch  # type: ignore[method-assign]
        run.run()

        assert run.draws == [(0.9, 1.0), (1.8, 2.0), (2.7, 3.0), (2.7, 3.0)]
        assert run.sleeps == [1.0, 2.0, 3.0, 3.0]

    def test_the_sleep_is_the_drawn_wait(self) -> None:
        daemon = _daemon(1, base_delay=4.0, max_delay=9.0)
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            daemon._accept_incoming = False
            daemon._process = _Process(0)  # type: ignore[assignment]

        run.launch = launch  # type: ignore[method-assign]
        run.uniform = lambda low, high: 3.5  # type: ignore[method-assign]
        run.run()

        assert run.sleeps == [3.5]

    def test_giving_up_names_the_number_of_deaths_and_stops_accepting(self) -> None:
        daemon = _daemon(1, max_attempts=2, reset_delay=1e9)
        run = _Run(daemon)

        run.run()

        assert daemon._failure == "The sandbox process died 3 times; it is no longer restarted."
        assert daemon._accept_incoming is False
        assert daemon.is_started is False
        assert len(run.launches) == 2

    def test_the_counter_is_reset_when_the_last_restart_is_old(self) -> None:
        daemon = _daemon(1, max_attempts=1, reset_delay=10.0)
        daemon._last_reset = time.time() - 100
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            run.launches.append((rules, kwargs))
            daemon._accept_incoming = False
            daemon._process = _Process(0)  # type: ignore[assignment]

        run.launch = launch  # type: ignore[method-assign]
        run.run()

        assert daemon._failure is None
        assert len(run.launches) == 1

    def test_the_last_restart_time_is_refreshed_after_the_wait(self) -> None:
        daemon = _daemon(1)
        daemon._last_reset = 0.0
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            daemon._accept_incoming = False
            daemon._process = _Process(0)  # type: ignore[assignment]

        run.launch = launch  # type: ignore[method-assign]
        before = time.time()
        run.run()

        assert daemon._last_reset >= before

    def test_a_cancelled_wait_ends_quietly(self) -> None:
        daemon = _daemon(asyncio.CancelledError())
        run = _Run(daemon)

        run.run()

        assert run.launches == []
        assert daemon._failure is None

    def test_a_cancelled_launch_ends_quietly(self) -> None:
        daemon = _daemon(1)
        run = _Run(daemon)

        async def launch(rules: Any, **kwargs: Any) -> None:
            raise asyncio.CancelledError()

        run.launch = launch  # type: ignore[method-assign]
        run.run()

        assert daemon._failure is None

    def test_the_attempt_counter_starts_at_zero_when_the_loop_starts(self) -> None:
        daemon = _daemon(0, accept=False)
        daemon._attempts = 7

        _Run(daemon).run()

        assert daemon._attempts == 0
