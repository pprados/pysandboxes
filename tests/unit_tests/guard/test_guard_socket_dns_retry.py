# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A resolver hiccup must not invalidate a ``net=`` rule.

``net=`` rules are resolved when the configuration is parsed, so a resolver
that answers late -- one still starting up in a container, or under load --
turned a perfectly valid profile into a fatal ``ConfigSyntaxError`` claiming
the rule did not resolve to any network.

A transient failure (``EAI_AGAIN``, ``EAI_SYSTEM``) is retried; a name that
does not exist (``EAI_NONAME``) is not, because that one is the rule author's
mistake and must surface at once. When the retries are exhausted the error
message says the resolver failed, so the reader does not go looking for a
mistake in the profile.
"""

import socket
from pathlib import Path
from unittest.mock import patch

from pysandboxes.guard_socket import parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

_RULE = "net=ALLOW|TCP|www.example.test|443|OUT"
_DENY_RULE = "net=DENY|TCP|www.example.test|443|OUT"

_TRANSIENT = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
_PERMANENT = socket.gaierror(socket.EAI_NONAME, "Name or service not known")

_RESOLVED = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))]


def _parse(side_effect: object, rule: str = _RULE) -> tuple[list[ErrorMsg], dict, int, list[float], tuple]:
    """Parse ``rule`` with the system resolver replaced by ``side_effect``."""
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(rule, Path(), 1)]
    with (
        patch("pysandboxes.guard_socket.socket.getaddrinfo", side_effect=side_effect) as resolver,
        patch("pysandboxes.guard_socket.time.sleep") as sleeper,
    ):
        socket_rules, _, pin_dns = parse_rules(lines, errors)
    delays = [call.args[0] for call in sleeper.call_args_list]
    return errors, dict(pin_dns), resolver.call_count, delays, tuple(socket_rules)


def test_transient_failure_is_retried() -> None:
    errors, pin_dns, calls, _, _ = _parse([_TRANSIENT, _RESOLVED])
    assert not errors
    assert calls == 2
    assert {info[4][0] for info in pin_dns["www.example.test"]} == {"93.184.216.34"}


def test_permanent_failure_is_not_retried() -> None:
    errors, _, calls, _, _ = _parse(_PERMANENT, _DENY_RULE)
    assert calls == 1
    assert len(errors) == 1
    assert "does not resolve to any network" in errors[0][0]


def test_exhausted_retries_blame_the_resolver() -> None:
    errors, _, calls, delays, _ = _parse(_TRANSIENT, _DENY_RULE)
    assert calls == 3
    assert delays == [0.2, 0.4]
    assert len(errors) == 1
    assert "failed temporarily" in errors[0][0]
    assert "does not resolve to any network" not in errors[0][0]


# A machine with no resolver at all must still be able to start: an ``ALLOW``
# whose name cannot be resolved grants nothing, so dropping it leaves the
# implicit default policy in charge and the process stays fail-closed. A
# ``DENY`` is the opposite -- dropping one would lift a restriction its author
# wrote on purpose -- so that one stays fatal.


def test_unresolvable_allow_is_not_fatal() -> None:
    errors, _, _, _, socket_rules = _parse(_PERMANENT)
    assert not errors
    assert socket_rules == ()


def test_allow_with_dead_resolver_is_not_fatal() -> None:
    errors, _, calls, delays, socket_rules = _parse(_TRANSIENT)
    assert not errors
    assert calls == 3
    assert delays == [0.2, 0.4]
    assert socket_rules == ()


def test_unresolvable_allow_does_not_widen_the_survivors() -> None:
    """A dropped rule must not hand its ports to the rules that did resolve."""
    errors: list[ErrorMsg] = []
    lines = [
        ConfigLine("net=ALLOW|TCP|www.example.test|443|OUT", Path(), 1),
        ConfigLine("net=ALLOW|TCP|127.0.0.1|8000|IN", Path(), 2),
    ]
    with patch("pysandboxes.guard_socket.socket.getaddrinfo", side_effect=_PERMANENT):
        socket_rules, _, _ = parse_rules(lines, errors)
    assert not errors
    surviving = tuple(socket_rules)
    assert len(surviving) == 1
    assert tuple(surviving[0][1][2]) == (8000,)


def test_tolerated_allow_is_claimed_not_left_unknown() -> None:
    """A dropped rule must not resurface as an unknown directive.

    ``parse_rules`` hands back the lines it does not own so the next guard can
    claim them; a line nobody claims is reported as an invalid rule. A net=
    rule that resolved to nothing was understood, so leaving it in that list
    turns a tolerated ALLOW back into the fatal config error this change exists
    to remove.
    """
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(_RULE, Path(), 1)]
    with patch("pysandboxes.guard_socket.socket.getaddrinfo", side_effect=_PERMANENT):
        socket_rules, unclaimed, _ = parse_rules(lines, errors)
    assert not errors
    assert tuple(socket_rules) == ()
    assert list(unclaimed) == []
