# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A name that cannot be resolved at connect time is refused, whatever the allow rules say."""

import socket
from pathlib import Path
from typing import Any

import pytest

from pysandboxes import guard_socket as gs
from pysandboxes.guard_socket import Direction, Kind
from pysandboxes.sb_types import ConfigLine

_FAULTS = [
    socket.EAI_NONAME,
    socket.EAI_AGAIN,
    socket.EAI_FAIL,
    socket.EAI_SERVICE,
]
if hasattr(socket, "EAI_SYSTEM"):  # POSIX only
    _FAULTS.append(socket.EAI_SYSTEM)


def _allow_everything() -> Any:
    socket_rules, _, _ = gs.parse_rules([ConfigLine("net=ALLOW|*|*|*|OUT", Path(), 1)], [])
    return socket_rules


@pytest.mark.parametrize("fault", _FAULTS)
def test_a_resolver_failure_refuses_the_connection_even_under_an_allow_all_rule(
    monkeypatch: pytest.MonkeyPatch, fault: int
) -> None:
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror(fault, "injected")

    monkeypatch.setattr(gs.socket, "getaddrinfo", failing)

    with pytest.raises(ValueError, match="resolution failed"):
        gs._check_address_with_rules(_allow_everything(), Kind.TCP, ("unreachable.example", 443), Direction.OUT)


def test_a_literal_address_needs_no_resolver_and_stays_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror(socket.EAI_AGAIN, "injected")

    monkeypatch.setattr(gs.socket, "getaddrinfo", failing)

    assert gs._check_address_with_rules(_allow_everything(), Kind.TCP, ("192.0.2.7", 443), Direction.OUT)
