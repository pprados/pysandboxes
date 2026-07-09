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

_TRANSIENT = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
_PERMANENT = socket.gaierror(socket.EAI_NONAME, "Name or service not known")

_RESOLVED = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))]


def _parse(side_effect: object) -> tuple[list[ErrorMsg], dict, int, list[float]]:
    """Parse ``_RULE`` with the system resolver replaced by ``side_effect``."""
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(_RULE, Path(), 1)]
    with (
        patch("pysandboxes.guard_socket.socket.getaddrinfo", side_effect=side_effect) as resolver,
        patch("pysandboxes.guard_socket.time.sleep") as sleeper,
    ):
        _, _, pin_dns = parse_rules(lines, errors)
    delays = [call.args[0] for call in sleeper.call_args_list]
    return errors, dict(pin_dns), resolver.call_count, delays


def test_transient_failure_is_retried() -> None:
    errors, pin_dns, calls, _ = _parse([_TRANSIENT, _RESOLVED])
    assert not errors
    assert calls == 2
    assert {info[4][0] for info in pin_dns["www.example.test"]} == {"93.184.216.34"}


def test_permanent_failure_is_not_retried() -> None:
    errors, _, calls, _ = _parse(_PERMANENT)
    assert calls == 1
    assert len(errors) == 1
    assert "does not resolve to any network" in errors[0][0]


def test_exhausted_retries_blame_the_resolver() -> None:
    errors, _, calls, delays = _parse(_TRANSIENT)
    assert calls == 3
    assert delays == [0.2, 0.4]
    assert len(errors) == 1
    assert "failed temporarily" in errors[0][0]
    assert "does not resolve to any network" not in errors[0][0]
