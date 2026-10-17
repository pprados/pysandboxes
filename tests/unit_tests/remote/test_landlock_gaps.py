# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The Landlock ABI handling, ruleset and path list, with the syscalls replaced by a recorder."""

import os
import site
import sys
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.remote import landlock_daemon as ll
from pysandboxes.sb_types import ConfigLine, Envs

_CONFIG = ConfigLine("x", Path(), 1)


def _socket_rule(
    ports: Any,
    *,
    action: Action = Action.ALLOW,
    kinds: tuple[Kind, ...] = (Kind.TCP,),
    directions: tuple[Direction, ...] = (Direction.OUT,),
) -> SocketRule:
    return SocketRule(action, SocketMask(kinds, IPv4Network("0.0.0.0/0"), ports), directions, _CONFIG)


class TestAvailability:
    def test_a_missing_syscall_table_means_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ll, "_LANDLOCK_RESTRICT_SELF", -1)

        assert ll._landlock_available() is False

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_only_linux_has_landlock(self, monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
        monkeypatch.setattr(ll, "_LANDLOCK_RESTRICT_SELF", 446)
        monkeypatch.setattr(ll, "_get_landlock_abi_version", lambda: 4)
        monkeypatch.setattr(sys, "platform", platform)

        assert ll._landlock_available() is False

    @pytest.mark.parametrize(("abi", "available"), [(4, True), (1, False), (0, False)])
    def test_the_abi_version_decides_on_linux(self, monkeypatch: pytest.MonkeyPatch, abi: int, available: bool) -> None:
        monkeypatch.setattr(ll, "_LANDLOCK_RESTRICT_SELF", 446)
        monkeypatch.setattr(ll, "_get_landlock_abi_version", lambda: abi)
        monkeypatch.setattr(sys, "platform", "linux")

        assert ll._landlock_available() is (abi > 0)
        assert ll.landlock_user_available() is available

    @pytest.mark.parametrize(("abi", "available"), [(4, True), (3, False), (0, False)])
    def test_network_confinement_requires_landlock_abi_four(
        self, monkeypatch: pytest.MonkeyPatch, abi: int, available: bool
    ) -> None:
        monkeypatch.setattr(ll, "_LANDLOCK_RESTRICT_SELF", 446)
        monkeypatch.setattr(ll, "_get_landlock_abi_version", lambda: abi)
        monkeypatch.setattr(sys, "platform", "linux")

        assert ll.landlock_user_available() is available

    @pytest.mark.parametrize(
        ("available", "reason"), [(True, None), (False, "Landlock requires Linux with filesystem support")]
    )
    def test_the_provider_reports_why_it_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, available: bool, reason: str | None
    ) -> None:
        monkeypatch.setattr(ll, "landlock_user_available", lambda: available)

        result = ll.LandlockSSEDaemon.unavailable_reason()

        assert (result is None) if reason is None else (reason in (result or ""))


class TestAbiVersion:
    def _version(
        self, monkeypatch: pytest.MonkeyPatch, result: Any, *, create: int = 444, platform: str = "linux"
    ) -> int:
        def syscall(*args: Any) -> int:
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(ll, "_LANDLOCK_CREATE_RULESET", create)
        monkeypatch.setattr(ll, "syscall", syscall, raising=False)
        monkeypatch.setattr(sys, "platform", platform)
        return ll._get_landlock_abi_version()

    @pytest.mark.parametrize("failure", [-1, -38, OSError("no")])
    def test_a_failing_syscall_means_unsupported(self, monkeypatch: pytest.MonkeyPatch, failure: Any) -> None:
        assert self._version(monkeypatch, failure) == 0

    def test_without_the_syscall_number_or_off_linux_it_is_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._version(monkeypatch, 6, create=-1) == 0
        assert self._version(monkeypatch, 6, platform="darwin") == 0


class TestNetPorts:
    def test_ports_outside_the_valid_range_are_dropped_and_the_edges_kept(self) -> None:
        rules = (_socket_rule((0, 65535, 65536, 70000, -1, 80)),)

        assert ll._collect_landlock_net_ports(rules) == [(0, False, True), (80, False, True), (65535, False, True)]

    def test_a_range_is_clipped_to_the_valid_ports(self) -> None:
        rules = (_socket_rule(range(65534, 65540)),)

        assert ll._collect_landlock_net_ports(rules) == [(65534, False, True), (65535, False, True)]

    def test_a_rule_that_grants_nothing_does_not_hide_the_following_ones(self) -> None:
        rules = (
            _socket_rule((1,), action=Action.DENY),
            _socket_rule((2,), kinds=(Kind.UDP,)),
            _socket_rule((3,), directions=()),
            _socket_rule((4,), directions=(Direction.IN, Direction.OUT)),
        )

        assert ll._collect_landlock_net_ports(rules) == [(4, True, True)]


class _Recorder:
    """Stands for the syscall and libc functions `_apply_landlock` drives."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        abi: int,
        create_result: int = 7,
        restrict_result: int = 0,
        add_result: int = 0,
        open_result: int = 9,
    ):
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.opened: list[bytes] = []
        self.create_result = create_result
        self.restrict_result = restrict_result
        self.add_result = add_result
        self.open_result = open_result

        def syscall(number: int, *args: Any) -> int:
            self.calls.append((self._name(number), args))
            if number == ll._LANDLOCK_CREATE_RULESET:
                return self.create_result
            if number == ll._LANDLOCK_RESTRICT_SELF:
                return self.restrict_result
            return self.add_result

        libc = MagicMock()

        def open_path(path: bytes, flags: int) -> int:
            self.opened.append(path)
            return self.open_result

        libc.open.side_effect = open_path
        monkeypatch.setattr(ll, "syscall", syscall, raising=False)
        monkeypatch.setattr(ll, "libc", libc, raising=False)
        monkeypatch.setattr(ll, "_get_landlock_abi_version", lambda: abi)
        monkeypatch.setattr(ll, "_LANDLOCK_CREATE_RULESET", 1001)
        monkeypatch.setattr(ll, "_LANDLOCK_ADD_RULE", 1002)
        monkeypatch.setattr(ll, "_LANDLOCK_RESTRICT_SELF", 1003)
        self.libc = libc

    @staticmethod
    def _name(number: int) -> str:
        return {1001: "create", 1002: "add", 1003: "restrict"}[number]

    def attr(self, name: str, index: int = 0) -> Any:
        matching = [args for call, args in self.calls if call == name]
        return matching[index][2 if name == "add" else 0]._obj if name != "restrict" else None

    def adds(self) -> list[Any]:
        return [args for call, args in self.calls if call == "add"]


class TestApplyLandlock:
    @pytest.mark.parametrize(
        ("abi", "refer", "truncate"),
        [(1, False, False), (2, True, False), (3, True, True), (6, True, True)],
    )
    def test_the_filesystem_rights_follow_the_kernel_abi(
        self, monkeypatch: pytest.MonkeyPatch, abi: int, refer: bool, truncate: bool
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=abi)

        ll._apply_landlock([])

        handled = recorder.attr("create").handled_access_fs
        assert bool(handled & ll.LANDLOCK_ACCESS_FS_REFER) is refer
        assert bool(handled & ll.LANDLOCK_ACCESS_FS_TRUNCATE) is truncate

    @pytest.mark.parametrize(
        ("abi", "ports", "handled_net"),
        [
            (4, [(80, False, True)], ll.HANDLED_ACCESS_NET),
            (5, [(80, False, True)], ll.HANDLED_ACCESS_NET),
            (6, [(80, False, True)], ll.HANDLED_ACCESS_NET),
            (4, None, 0),
        ],
    )
    def test_the_network_is_handled_from_abi_4_when_ports_are_given(
        self, monkeypatch: pytest.MonkeyPatch, abi: int, ports: Any, handled_net: int
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=abi)

        ll._apply_landlock([], ports)

        assert recorder.attr("create").handled_access_net == handled_net

    def test_an_empty_port_list_handles_network_access_but_adds_no_allow_rules(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([], [])

        assert recorder.attr("create").handled_access_net == ll.HANDLED_ACCESS_NET
        assert not [c for c in recorder.adds() if c[2]._obj.__class__.__name__.endswith("PortAttr")]

    def test_network_restriction_fails_closed_when_abi_four_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _Recorder(monkeypatch, abi=3)

        with pytest.raises(OSError, match="network restriction requires Landlock ABI v4"):
            ll._apply_landlock([], [])

    @pytest.mark.parametrize(("abi", "scoped"), [(5, 0), (6, ll.LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET)])
    def test_abstract_unix_sockets_are_scoped_from_abi_6(
        self, monkeypatch: pytest.MonkeyPatch, abi: int, scoped: int
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=abi)

        ll._apply_landlock([])

        assert recorder.attr("create").scoped == scoped

    def test_a_ruleset_that_cannot_be_created_is_an_error_and_descriptor_zero_is_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _Recorder(monkeypatch, abi=4, create_result=-1)
        with pytest.raises(OSError, match="landlock_create_ruleset"):
            ll._apply_landlock([])

        recorder = _Recorder(monkeypatch, abi=4, create_result=0)
        ll._apply_landlock([])
        assert [call for call, _ in recorder.calls][-1] == "restrict"

    def test_a_ruleset_that_cannot_restrict_the_process_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _Recorder(monkeypatch, abi=4, restrict_result=-1)

        with pytest.raises(OSError, match="landlock_restrict_self"):
            ll._apply_landlock([])

    def test_paths_are_opened_absolute_and_granted_read_only_or_read_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([("", False), (".", False), ("rel/dir", True), ("/abs/ro", False), ("/abs/rw", True)])

        opened = [path.decode() for path in recorder.opened]
        assert opened[:5] == [str(tmp_path), str(tmp_path), str(tmp_path / "rel" / "dir"), "/abs/ro", "/abs/rw"]
        grants = [call[2]._obj.allowed_access for call in recorder.adds()[:5]]
        assert grants[2] == ll.ACCESS_RW & recorder.attr("create").handled_access_fs
        assert grants[3] == ll.ACCESS_RO & recorder.attr("create").handled_access_fs
        assert grants[4] == grants[2]

    def test_the_ports_get_bind_and_connect_rights_and_a_port_without_rights_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([], [(80, True, False), (81, False, True), (82, True, True), (83, False, False)])

        net = [
            (c[2]._obj.port, c[2]._obj.allowed_access)
            for c in recorder.adds()
            if c[2]._obj.__class__.__name__.endswith("PortAttr")
        ]
        assert net == [
            (80, ll.LANDLOCK_ACCESS_NET_BIND_TCP),
            (81, ll.LANDLOCK_ACCESS_NET_CONNECT_TCP),
            (82, ll.LANDLOCK_ACCESS_NET_BIND_TCP | ll.LANDLOCK_ACCESS_NET_CONNECT_TCP),
        ]

    def test_a_port_without_rights_does_not_hide_the_following_ones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([], [(83, False, False), (84, True, False)])

        ports = [c[2]._obj.port for c in recorder.adds() if c[2]._obj.__class__.__name__.endswith("PortAttr")]
        assert ports == [84]

    def test_network_rules_fail_closed_when_the_kernel_does_not_handle_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _Recorder(monkeypatch, abi=3)

        with pytest.raises(OSError, match="network restriction requires Landlock ABI v4"):
            ll._apply_landlock([], [(80, True, True)])


class TestProviderActivation:
    def test_no_socket_rules_still_activate_an_empty_default_deny_network_policy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(ll, "_landlock_available", lambda: True)
        monkeypatch.setattr(ll, "_set_no_new_privs", lambda: None)
        monkeypatch.setattr(ll, "_collect_landlock_paths", lambda *args: [])

        def apply(paths: list[tuple[str, bool]], net_ports: list[tuple[int, bool, bool]] | None = None) -> None:
            captured["net_ports"] = net_ports

        monkeypatch.setattr(ll, "_apply_landlock", apply)

        ll.LandlockSSEDaemon("token").update_rules_and_activate(envs=Envs({}), all_rules=EmptyRules, temp=tmp_path)

        assert captured["net_ports"] == []

    def test_the_resolver_directories_are_read_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([])

        resolv_dirs = {str(Path("/etc/resolv.conf").resolve().parent), str(Path("/etc/resolv.conf").parent)}
        opened = [path.decode() for path in recorder.opened]
        for directory in resolv_dirs:
            grant = recorder.adds()[opened.index(directory)][2]._obj.allowed_access
            assert grant == ll.ACCESS_RO & recorder.attr("create").handled_access_fs

    def test_a_relative_path_is_anchored_at_the_current_directory_whatever_its_first_character(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        recorder = _Recorder(monkeypatch, abi=4)

        ll._apply_landlock([("-dash", False)])

        assert str(tmp_path / "-dash") in [path.decode() for path in recorder.opened]

    def test_descriptor_zero_is_a_valid_parent_and_a_negative_one_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zero = _Recorder(monkeypatch, abi=4, open_result=0)
        ll._apply_landlock([("/abs/zero", False)])
        granted_zero = [c[2]._obj.parent_fd for c in zero.adds() if hasattr(c[2]._obj, "parent_fd")]
        failed = _Recorder(monkeypatch, abi=4, open_result=-1)
        ll._apply_landlock([("/abs/failed", False)])

        assert 0 in granted_zero
        assert not [c for c in failed.adds() if hasattr(c[2]._obj, "parent_fd")]

    def test_a_path_that_cannot_be_opened_does_not_hide_the_following_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(monkeypatch, abi=4)
        recorder.libc.open.side_effect = lambda path, flags: -1 if path == b"/abs/failed" else 9

        ll._apply_landlock([("/abs/failed", False), ("/abs/ok", False)])

        granted = [c[2]._obj.parent_fd for c in recorder.adds() if hasattr(c[2]._obj, "parent_fd")]
        assert granted.count(9) >= 1 and -1 not in granted

    def test_a_rule_the_kernel_refuses_is_reported_and_an_accepted_one_is_not(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger=ll.logger.name):
            _Recorder(monkeypatch, abi=4, add_result=0)
            ll._apply_landlock([("/abs/ok", False)], [(80, True, True)])
            assert not [r for r in caplog.records if "landlock_add_rule" in r.getMessage()]

            _Recorder(monkeypatch, abi=4, add_result=-1)
            ll._apply_landlock([("/abs/refused", False)], [(81, True, True)])

        messages = [r.getMessage() for r in caplog.records if "landlock_add_rule" in r.getMessage()]
        assert any("/abs/refused" in m for m in messages)
        assert any("port 81" in m for m in messages)

    def test_any_nonzero_answer_of_restrict_self_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _Recorder(monkeypatch, abi=4, restrict_result=1)

        with pytest.raises(OSError, match="landlock_restrict_self"):
            ll._apply_landlock([])


class TestCollectPaths:
    def _paths(self, tmp_path: Path, *rules: FSExposeRule) -> dict[str, str]:
        collected = ll._collect_landlock_paths(
            EmptyRules._replace(file_rules=tuple(rules)), tmp_path / "temp", str(tmp_path / "cwd")
        )
        return dict(collected)

    def test_the_system_directories_and_the_temp_directory_are_granted(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)

        assert paths["/usr"] == "ro"
        assert paths["/etc"] == "ro"
        assert paths["/dev"] == "rw"
        assert paths[str(tmp_path / "temp")] == "rw"
        assert paths[os.path.dirname(os.path.realpath(sys.executable))] in ("ro", "rw")

    def test_the_python_path_entries_that_exist_are_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = tmp_path / "entry"
        entry.mkdir()
        packages = tmp_path / "packages"
        packages.mkdir()
        monkeypatch.setattr(sys, "path", ["", str(tmp_path / "missing"), str(entry)])
        monkeypatch.setattr(site, "getsitepackages", lambda: ["", str(tmp_path / "missing"), str(packages)])

        paths = self._paths(tmp_path)

        assert paths[str(entry)] == "ro"
        assert paths[str(packages)] == "ro"
        assert str(tmp_path / "missing") not in paths
        assert "" not in paths

    def test_a_read_only_path_granted_twice_stays_read_only(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path, FSExposeRule("/usr", False, _CONFIG), FSExposeRule("/usr", False, _CONFIG))

        assert paths["/usr"] == "ro"

    def test_write_access_wins_whatever_the_order(self, tmp_path: Path) -> None:
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()

        paths = self._paths(
            tmp_path,
            FSExposeRule(str(first), False, _CONFIG),
            FSExposeRule(str(first), True, _CONFIG),
            FSExposeRule(str(second), True, _CONFIG),
            FSExposeRule(str(second), False, _CONFIG),
        )

        assert paths[str(first)] == "rw"
        assert paths[str(second)] == "rw"

    def test_a_relative_rule_is_made_absolute_and_the_current_directory_is_kept_even_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "rel").mkdir()

        paths = self._paths(tmp_path, FSExposeRule("rel", False, _CONFIG), FSExposeRule(".", False, _CONFIG))

        assert paths[str(tmp_path / "rel")] == "ro"
        assert paths[str(tmp_path / "cwd")] == "ro"

    def test_a_path_that_does_not_exist_is_not_granted(self, tmp_path: Path) -> None:
        assert str(tmp_path / "nowhere") not in self._paths(
            tmp_path, FSExposeRule(str(tmp_path / "nowhere"), True, _CONFIG)
        )
