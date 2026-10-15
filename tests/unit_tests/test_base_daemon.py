# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The initial state of a daemon and what the base shutdown resets."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.base_daemon import BaseDaemon, FakeDaemon
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLine, Envs


def test_a_new_daemon_is_stopped_and_accepts_no_incoming_connection() -> None:
    daemon = FakeDaemon("token")

    assert daemon.is_started is False
    assert daemon.token == "token"
    assert daemon._accept_incoming is False


def test_the_base_shutdown_stops_accepting_incoming_connections() -> None:
    daemon = FakeDaemon("token")
    daemon._accept_incoming = True

    asyncio.run(BaseDaemon._shutdown(daemon))

    assert daemon._accept_incoming is False


def test_the_base_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="abstract"):
        BaseDaemon("token")  # type: ignore[abstract]


def test_the_constructor_accepts_and_ignores_provider_arguments() -> None:
    daemon = FakeDaemon("token", host="elsewhere", anything=1)

    assert daemon.token == "token"
    assert daemon.is_started is False


def test_is_started_reflects_the_internal_flag() -> None:
    daemon = FakeDaemon("token")

    daemon._is_started = True

    assert daemon.is_started is True


def test_a_provider_is_available_by_default() -> None:
    assert BaseDaemon.unavailable_reason() is None
    assert FakeDaemon.unavailable_reason() is None


def test_the_default_rule_parsing_takes_nothing_and_hands_back_every_rule() -> None:
    rules = [ConfigLine("env=ALLOW|X", Path("p"), 1)]
    errors: list[Any] = []

    params, rest = FakeDaemon("token").parse_rules(rules, errors)

    assert params == ImmutableDict({}) and isinstance(params, ImmutableDict)
    assert rest is rules
    assert errors == []


def test_the_abstract_operations_raise_not_implemented_when_reached_through_super(tmp_path: Path) -> None:
    daemon = FakeDaemon("token")
    update: Any = BaseDaemon.update_rules_and_activate  # pyright: ignore[reportAbstractUsage]
    start: Any = BaseDaemon._start  # pyright: ignore[reportAbstractUsage]
    stop: Any = BaseDaemon._stop  # pyright: ignore[reportAbstractUsage]
    acall: Any = BaseDaemon.async_call_in_sandbox  # pyright: ignore[reportAbstractUsage]
    call: Any = BaseDaemon.call_in_sandbox  # pyright: ignore[reportAbstractUsage]

    with pytest.raises(NotImplementedError):
        update(daemon, envs=Envs({}), all_rules=EmptyRules, temp=tmp_path)
    with pytest.raises(NotImplementedError):
        asyncio.run(start(daemon, EmptyRules, envs={}, log_level=0, init_fn=None))
    with pytest.raises(NotImplementedError):
        asyncio.run(stop(daemon, 1))
    with pytest.raises(NotImplementedError):
        asyncio.run(acall(daemon, print, False))
    with pytest.raises(NotImplementedError):
        call(daemon, print, False)


class TestFakeDaemon:
    def test_it_leaves_the_rules_as_they_are(self, tmp_path: Path) -> None:
        daemon = FakeDaemon("token")

        assert daemon.update_rules_and_activate(envs=Envs({}), all_rules=EmptyRules, temp=tmp_path) is EmptyRules

    def test_start_then_stop_then_shutdown_move_the_started_flag(self) -> None:
        daemon = FakeDaemon("token")

        asyncio.run(daemon._start(EmptyRules, envs={}, log_level=0, init_fn=None))
        assert daemon.is_started is True
        asyncio.run(daemon._stop(1))
        assert daemon.is_started is False

        daemon._is_started = True
        asyncio.run(daemon._shutdown())
        assert daemon.is_started is False

    @pytest.mark.parametrize("graceful", [True, False])
    def test_shutdown_stops_it_whatever_the_mode(self, graceful: bool) -> None:
        daemon = FakeDaemon("token")
        daemon._is_started = True

        asyncio.run(daemon._shutdown(graceful))

        assert daemon.is_started is False

    def test_a_call_says_why_it_cannot_run(self) -> None:
        daemon = FakeDaemon("token")

        with pytest.raises(NotImplementedError, match="Fake daemon, because you use `python-sb`"):
            daemon.call_in_sandbox(print, False)
        with pytest.raises(NotImplementedError, match="Fake daemon, because you use `python-sb`"):
            asyncio.run(daemon.async_call_in_sandbox(print, False))
