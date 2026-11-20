# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path

from pysandboxes.remote import ipv6_route

ZERO = "0" * 32
DEFAULT = f"{ZERO} 00 {ZERO} 00 {ZERO} 00000100 00000001 00000000 00000001     tap0\n"
LOOPBACK_DEFAULT = f"{ZERO} 00 {ZERO} 00 {ZERO} ffffffff 00000001 00000000 00200200       lo\n"
LINK_LOCAL = f"fe80{'0' * 28} 40 {ZERO} 00 {ZERO} 00000100 00000001 00000000 00000001     tap0\n"


def test_only_a_default_route_off_the_loopback_counts(tmp_path: Path) -> None:
    route = tmp_path / "ipv6_route"
    route.write_text(LINK_LOCAL + LOOPBACK_DEFAULT)
    assert not ipv6_route.has_default_route(str(route))
    route.write_text(LINK_LOCAL + LOOPBACK_DEFAULT + DEFAULT)
    assert ipv6_route.has_default_route(str(route))


def test_a_missing_route_file_is_no_route(tmp_path: Path) -> None:
    assert not ipv6_route.has_default_route(str(tmp_path / "none"))


def test_waiting_gives_up_after_the_timeout(tmp_path: Path) -> None:
    assert ipv6_route.wait_default_route(2**22 + 1, timeout=0.05) is False


def test_waiting_ends_when_the_route_appears(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen = iter([False, False, True])
    monkeypatch.setattr(ipv6_route, "has_default_route", lambda _: next(seen))
    assert ipv6_route.wait_default_route(1, timeout=5.0) is True
