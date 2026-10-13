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


# %% Mutation-testing gaps


def test_refuse_a_name_no_rule_can_allow_ignores_an_empty_name(resolver: Mock) -> None:
    """An empty name is not a real query: the early-return guard must still fire outside learning mode."""
    gs._refuse_a_name_no_rule_can_allow("")  # does not raise


def test_a_deny_only_rule_set_still_refuses_an_unlisted_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ALLOW rule at all must still refuse an unlisted name, not merely a narrow one."""
    monkeypatch.setattr(gs, "_rules_loaded", True)
    monkeypatch.setattr(
        gs,
        "_rules",
        (
            SocketRule(
                Action.DENY,
                SocketMask((Kind.TCP,), ip_network("0.0.0.0/0"), (443,)),
                (Direction.OUT,),
                ConfigLine("net=DENY|TCP|0.0.0.0/0|443|OUT", Path(), 0),
            ),
        ),
    )
    monkeypatch.setattr(gs, "_pin_dns", ImmutableDict({}))
    resolver = Mock(return_value=[PINNED])

    with pytest.raises(RuleSocketConnectionRefusedError, match="no net= rule names it"):
        gs._wrap_socket_getaddrinfo(resolver)("unlisted.example", 443)
    resolver.assert_not_called()


def test_a_name_no_rule_can_allow_is_refused_via_gethostbyname(resolver: Mock) -> None:
    gethostbyname_resolver = Mock(return_value="203.0.113.9")

    with pytest.raises(RuleSocketConnectionRefusedError, match="no net= rule names it"):
        gs._wrap_socket_gethostbyname(gethostbyname_resolver)("example.com")
    gethostbyname_resolver.assert_not_called()


def test_a_name_no_rule_can_allow_is_refused_via_gethostbyname_ex(resolver: Mock) -> None:
    gethostbyname_ex_resolver = Mock(return_value=("example.com", [], ["203.0.113.9"]))

    with pytest.raises(RuleSocketConnectionRefusedError, match="no net= rule names it"):
        gs._wrap_socket_gethostbyname_ex(gethostbyname_ex_resolver)("example.com")
    gethostbyname_ex_resolver.assert_not_called()


_WIDE_PIN = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.0", 0))


def test_a_wide_pinned_allow_rule_still_lets_an_unlisted_name_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wide ALLOW+OUT rule lets an unlisted name resolve even when its own network address is pinned."""
    monkeypatch.setattr(gs, "_rules_loaded", True)
    monkeypatch.setattr(gs, "_rules", (_allow_out("10.0.0.0/8"),))
    monkeypatch.setattr(gs, "_pin_dns", ImmutableDict({"pinned.example": (_WIDE_PIN,)}))

    gs._refuse_a_name_no_rule_can_allow("unlisted.example")  # does not raise
