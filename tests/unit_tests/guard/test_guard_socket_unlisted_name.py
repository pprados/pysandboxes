# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Regression: a name no `net=` rule can allow is refused at resolution, the same way under every provider.

Under bwrap, which isolates the network, such a name did not resolve at all: the code got "Name or service not
known" and nothing said a rule refused it, where subprocess resolved it and refused the connection.
"""

import socket
from ipaddress import ip_network
from pathlib import Path
from unittest.mock import Mock

import pytest

import pysandboxes.guard_socket as gs
from pysandboxes import RuleSocketConnectionRefusedError
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLine

PINNED = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 0))


def _allow_out(network: str) -> SocketRule:
    return SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network(network), (443,)),
        (Direction.OUT,),
        ConfigLine(f"net=ALLOW|TCP|{network}|443|OUT", Path(), 0),
    )


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(gs, "_rules_loaded", True)
    monkeypatch.setattr(gs, "_rules", (_allow_out("192.0.2.1/32"),))
    monkeypatch.setattr(gs, "_pin_dns", ImmutableDict({"allowed.test": (PINNED,)}))
    return Mock(return_value=[PINNED])


def test_a_name_no_rule_can_allow_is_refused_before_any_query(resolver: Mock) -> None:
    with pytest.raises(RuleSocketConnectionRefusedError, match="no net= rule names it"):
        gs._wrap_socket_getaddrinfo(resolver)("example.com", 443)
    resolver.assert_not_called()


def test_a_rule_wider_than_the_pinned_addresses_lets_the_name_resolve(
    resolver: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gs, "_rules", (_allow_out("192.0.2.1/32"), _allow_out("0.0.0.0/0")))
    gs._wrap_socket_getaddrinfo(resolver)("example.com", 443)
    resolver.assert_called_once()


@pytest.mark.parametrize("name", ["localhost", "127.0.0.1", "::1"])
def test_a_loopback_name_or_an_address_still_resolves(resolver: Mock, name: str) -> None:
    gs._wrap_socket_getaddrinfo(resolver)(name, 443)
    resolver.assert_called_once()


def test_a_pinned_name_is_answered_from_the_pin(resolver: Mock) -> None:
    assert gs._wrap_socket_getaddrinfo(resolver)("allowed.test", 443)[0][4] == ("192.0.2.1", 443)
    resolver.assert_not_called()
