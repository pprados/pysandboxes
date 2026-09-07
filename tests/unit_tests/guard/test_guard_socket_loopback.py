# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Loopback names stay usable in ``net=`` rules without a resolver.

``localhost`` and ``ip6-localhost`` name the loopback interface by
convention, but they are only resolvable through ``/etc/hosts``, and
that file is not guaranteed to carry them: Docker Desktop rewrites it
without the standard IPv6 block, and a minimal container image may ship
none of the entries. An unresolvable name silently grants nothing, so a
profile written against these names lost the access it meant to open
depending on the host it ran on.

The fallback keeps the names in the profile rather than forcing IP
literals, so the pinned-DNS path stays exercised and sandboxed code
still resolves them locally.
"""

import socket
from pathlib import Path
from unittest.mock import patch

from pysandboxes.guard_socket import parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

_GAI_ERROR = socket.gaierror(-2, "Name or service not known")


def _parse_without_resolver(*rules: str) -> tuple[list[ErrorMsg], dict]:
    """Parse rules with every system lookup failing."""
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(rule, Path(), ln) for ln, rule in enumerate(rules)]
    with (
        patch("pysandboxes.guard_socket.socket.getaddrinfo", side_effect=_GAI_ERROR),
        patch("pysandboxes.guard_socket.getaddrinfo", side_effect=_GAI_ERROR),
    ):
        _, _, pin_dns = parse_rules(lines, errors)
    return errors, dict(pin_dns)


def test_ip6_localhost_needs_no_resolver() -> None:
    errors, pin_dns = _parse_without_resolver("net=ALLOW|TCP|ip6-localhost|9999|IN")
    assert not errors
    addresses = {info[4][0] for info in pin_dns["ip6-localhost"]}
    assert addresses == {"::1"}
    assert {info[0] for info in pin_dns["ip6-localhost"]} == {socket.AF_INET6}


def test_localhost_needs_no_resolver() -> None:
    errors, pin_dns = _parse_without_resolver("net=ALLOW|TCP|localhost|9999|IN")
    assert not errors
    assert "127.0.0.1" in {info[4][0] for info in pin_dns["localhost"]}


def test_fallback_covers_stream_and_datagram() -> None:
    """UDP rules on these names must keep working.

    The patched ``getaddrinfo`` filters pinned entries by socket type,
    so a stream-only fallback would answer an UDP lookup with nothing.
    """
    errors, pin_dns = _parse_without_resolver(
        "net=ALLOW|UDP|ip6-localhost|12345|OUT",
        "net=ALLOW|UDP|localhost|12345|IN",
    )
    assert not errors
    for name in ("ip6-localhost", "localhost"):
        kinds = {info[1] for info in pin_dns[name]}
        assert socket.SOCK_STREAM in kinds
        assert socket.SOCK_DGRAM in kinds


def test_unknown_name_is_not_covered_by_the_fallback() -> None:
    """The fallback is loopback-only: other names must gain nothing from it.

    An unresolvable ``ALLOW`` is dropped rather than fatal, so the proof that
    the fallback stayed loopback-only is the absence of a pinned address, not
    a config error.
    """
    errors, pin_dns = _parse_without_resolver("net=ALLOW|TCP|nonexistent.example.com|80|OUT")
    assert not errors
    assert "nonexistent.example.com" not in pin_dns
