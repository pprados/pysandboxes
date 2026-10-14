# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The initial state of a daemon and what the base shutdown resets."""

import asyncio

from pysandboxes.base_daemon import BaseDaemon, FakeDaemon


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
