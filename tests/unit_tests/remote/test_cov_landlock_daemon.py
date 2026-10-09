# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Profile rules -> what the Landlock launcher is told to allow, without a Landlock kernel."""

from pathlib import Path
from typing import Any

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.guard_socket import parse_rules
from pysandboxes.remote import landlock_daemon
from pysandboxes.remote.landlock_daemon import _collect_landlock_net_ports, _collect_landlock_paths
from pysandboxes.sb_types import ConfigLine


def _ports(*lines: str) -> list[tuple[int, bool, bool]]:
    errors: list = []
    rules, _, _ = parse_rules([ConfigLine(line, Path(), i) for i, line in enumerate(lines)], errors)
    assert errors == []
    return _collect_landlock_net_ports(rules)


def test_only_allowed_tcp_ports_are_granted() -> None:
    assert _ports("net=DENY|TCP|*|22|OUT", "net=ALLOW|UDP|*|53|OUT") == []


def test_direction_maps_to_bind_and_connect() -> None:
    assert _ports("net=ALLOW|TCP|*|443|OUT", "net=ALLOW|TCP|*|0|IN") == [(0, True, False), (443, False, True)]


def test_bind_and_connect_on_one_port_merge_across_rules() -> None:
    assert _ports("net=ALLOW|TCP|*|80|IN", "net=ALLOW|TCP|*|80|OUT") == [(80, True, True)]


def test_a_port_range_grants_each_port() -> None:
    assert _ports("net=ALLOW|TCP|*|8000-8002|IN") == [(8000, True, False), (8001, True, False), (8002, True, False)]


def test_a_rule_naming_tcp_among_other_kinds_still_counts() -> None:
    assert _ports("net=ALLOW|TCP,UDP|*|80|IN,OUT") == [(80, True, True)]


def _rule(path: Path, write: bool) -> FSExposeRule:
    return FSExposeRule(path=str(path), write=write, config=ConfigLine(f"expose={path}", Path(), 0))


def _paths(tmp_path: Path, *rules: FSExposeRule) -> dict[str, str]:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    temp = tmp_path / "pipe-dir-not-created-yet"
    granted = dict(_collect_landlock_paths(EmptyRules._replace(file_rules=rules), temp, str(cwd)))
    assert granted[str(temp)] == "rw"
    return granted


@pytest.mark.parametrize(("write", "expected"), [(False, "ro"), (True, "rw")])
def test_current_directory_access_matches_explicit_rule(tmp_path: Path, write: bool, expected: str) -> None:
    cwd = tmp_path / "cwd"

    assert _paths(tmp_path, _rule(cwd, write))[str(cwd)] == expected


def test_an_exposed_path_gets_the_access_its_rule_names(tmp_path: Path) -> None:
    ro, rw = tmp_path / "ro", tmp_path / "rw"
    ro.mkdir()
    rw.mkdir()

    granted = _paths(tmp_path, _rule(ro, write=False), _rule(rw, write=True))

    assert granted[str(ro)] == "ro"
    assert granted[str(rw)] == "rw"


def test_a_later_read_only_rule_never_downgrades_write_access(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    assert _paths(tmp_path, _rule(data, write=True), _rule(data, write=False))[str(data)] == "rw"


def test_a_later_write_rule_upgrades_read_only_access(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    assert _paths(tmp_path, _rule(data, write=False), _rule(data, write=True))[str(data)] == "rw"


def test_a_path_that_does_not_exist_is_not_granted(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    assert str(missing) not in _paths(tmp_path, _rule(missing, write=True))


def test_a_path_is_granted_in_its_normal_form(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    granted = _paths(tmp_path, FSExposeRule(path=f"{data}/./", write=False, config=ConfigLine("", Path(), 0)))

    assert granted[str(data)] == "ro"
    assert f"{data}/./" not in granted


@pytest.mark.parametrize(("abi", "available"), [(8, True), (1, True), (-1, False)])
def test_landlock_is_available_only_when_the_abi_query_succeeds(
    monkeypatch: pytest.MonkeyPatch, abi: int, available: bool
) -> None:
    """Landlock disabled at boot (EOPNOTSUPP) or missing (ENOSYS) fails the ABI query: it cannot enforce."""
    monkeypatch.setattr(landlock_daemon, "_LANDLOCK_RESTRICT_SELF", 446)
    monkeypatch.setattr(landlock_daemon, "_LANDLOCK_CREATE_RULESET", 444)
    monkeypatch.setattr(landlock_daemon.sys, "platform", "linux")
    monkeypatch.setattr(landlock_daemon, "syscall", lambda *_: abi)
    assert landlock_daemon._landlock_available() is available


def test_landlock_is_unavailable_without_the_syscalls_or_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(landlock_daemon, "_LANDLOCK_RESTRICT_SELF", -1)
    assert landlock_daemon._landlock_available() is False

    monkeypatch.setattr(landlock_daemon, "_LANDLOCK_RESTRICT_SELF", 446)
    monkeypatch.setattr(landlock_daemon.sys, "platform", "darwin")
    assert landlock_daemon._landlock_available() is False


@pytest.mark.parametrize(("abi", "scoped"), [(6, 1), (8, 1), (5, 0)])
def test_abstract_unix_sockets_outside_the_sandbox_are_scoped_out(
    monkeypatch: pytest.MonkeyPatch, abi: int, scoped: int
) -> None:
    """From ABI 6, the ruleset forbids connecting to an abstract Unix socket created outside the sandbox."""
    seen: list[int] = []

    def fake_syscall(_nr: int, attr: Any, *_args: Any) -> int:
        seen.append(attr._obj.scoped)
        return -1

    monkeypatch.setattr(landlock_daemon, "_get_landlock_abi_version", lambda: abi)
    monkeypatch.setattr(landlock_daemon, "syscall", fake_syscall)
    with pytest.raises(OSError):
        landlock_daemon._apply_landlock([])
    assert seen == [scoped]
