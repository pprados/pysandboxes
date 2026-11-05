# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The channel on a TCP port: forced by the profile, or left by ``auto`` where the platform has no Unix socket."""

import socket
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandboxes
from pysandboxes.remote import client_subprocess_sse_daemon as csd

from .test_rpc import sync_function

plain_profile = Path(__file__).parent / "py-sandbox-test.profile"
tcp_profile = Path(__file__).parent / "py-sandbox-tcp.profile"


@pytest.fixture
def bound_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the path of every socket the host binds for the sandbox."""
    paths: list[str] = []
    original = csd.listen_socket

    def recording(endpoint: Any) -> Any:
        paths.append(endpoint.path)
        return original(endpoint)

    monkeypatch.setattr(csd, "listen_socket", recording)
    return paths


def test_tcp_can_be_forced(bound_paths: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OS_SANDBOX", "subprocess")

    with sandboxes(sandboxes_config=tcp_profile):
        assert sync_function("a", b="3") == "a 3"

    assert bound_paths == []


# Defined, not skipped, where the platform has AF_UNIX: PYSANDBOXES_FAIL_ON_SKIP fails a skipped run.
if not hasattr(socket, "AF_UNIX"):

    def test_without_af_unix_the_channel_stays_on_tcp(bound_paths: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_SANDBOX", "subprocess")

        with sandboxes(sandboxes_config=plain_profile):
            assert sync_function("a", b="5") == "a 5"

        assert bound_paths == []
