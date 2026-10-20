# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Guards and helpers of `pysandboxes.remote.tools` that the other tests leave unobserved."""

import builtins
import io
import ipaddress
import pickle
import platform
import subprocess
import sys
import uuid
import zoneinfo
from typing import Any
from unittest.mock import MagicMock

import pytest

from pysandboxes.remote import tools
from pysandboxes.remote.tools import (
    RestrictedUnpicklingError,
    _get_default_interface_via_ip,
    _prescan,
    _value_getattr,
    _ValueUnpickler,
    descriptor_predicate,
    exception_predicate,
    get_bridge_interfaces,
    get_default_interface,
    get_dns_servers,
    get_upstream_dns,
    get_venv,
    result_predicate,
    suggest_package_installation,
    unshare_user_namespace_available,
    value_predicate,
)

_PROTO = b"\x80\x04"
_STOP = b"."


class _Plain:
    pass


class TestPrescanMarkBudget:
    def test_marks_separated_by_other_opcodes_still_count(self) -> None:
        data = _PROTO + b"(N" * (tools._MAX_MARK_DEPTH + 10) + _STOP

        with pytest.raises(RestrictedUnpicklingError, match="MARK budget"):
            _prescan(data)

    def test_a_balanced_nesting_is_accepted(self) -> None:
        _prescan(_PROTO + b"(" * 5 + b"t" * 5 + _STOP)


class TestValueGetattr:
    def test_only_the_zoneinfo_constructor_is_reachable(self) -> None:
        assert _value_getattr(zoneinfo.ZoneInfo, "_unpickle") == zoneinfo.ZoneInfo._unpickle  # type: ignore[attr-defined]

    @pytest.mark.parametrize("name", ["_aaa", "_unpickl", "_zzz", "unlink"])
    def test_every_other_attribute_is_refused(self, name: str) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="refused"):
            _value_getattr(zoneinfo.ZoneInfo, name)


class TestValueUnpicklerFindClass:
    def _unpickler(self) -> _ValueUnpickler:
        return _ValueUnpickler(pickle.dumps(1), value_predicate)

    def test_builtins_getattr_is_the_restricted_getattr(self) -> None:
        assert self._unpickler().find_class("builtins", "getattr") is _value_getattr

    @pytest.mark.parametrize(("module", "name"), [("os", "getattr"), ("abc", "getattr"), ("builtins", "eval")])
    def test_a_getattr_of_another_module_or_another_builtin_is_not(self, module: str, name: str) -> None:
        with pytest.raises(RestrictedUnpicklingError):
            self._unpickler().find_class(module, name)


class TestPredicates:
    def test_exception_channel_accepts_only_tblib_modules_and_exceptions(self) -> None:
        assert exception_predicate("tblib", "Traceback", _Plain)
        assert exception_predicate("tblib.pickling_support", "x", _Plain)
        assert exception_predicate("builtins", "ValueError", ValueError)
        assert not exception_predicate("uuid", "UUID", uuid.UUID)
        assert not exception_predicate("zoneinfo", "ZoneInfo", zoneinfo.ZoneInfo)

    def test_descriptor_channel_accepts_only_tblib(self) -> None:
        assert descriptor_predicate("tblib", "Traceback", _Plain)
        assert descriptor_predicate("tblib.x", "Traceback", _Plain)
        assert not descriptor_predicate("uuid", "UUID", uuid.UUID)
        assert not descriptor_predicate("zoneinfo", "ZoneInfo", zoneinfo.ZoneInfo)

    def test_result_channel_refuses_a_denied_builtin_only_under_builtins(self) -> None:
        assert not result_predicate("builtins", "eval", builtins.eval)
        assert result_predicate("myapp", "eval", _Plain)
        assert result_predicate("zoneinfo", "exec", _Plain)
        assert result_predicate("abc", "eval", _Plain)


class TestGetVenv:
    def test_outside_a_venv_the_environment_variable_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "prefix", "".join(["/base", "/python"]))
        monkeypatch.setattr(sys, "base_prefix", "".join(["/base", "/python"]))
        monkeypatch.setenv("VIRTUAL_ENV", "/from/env")

        assert get_venv() == "/from/env"

    def test_inside_a_venv_its_prefix_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "prefix", "/venv")
        monkeypatch.setattr(sys, "base_prefix", "/base")
        monkeypatch.setenv("VIRTUAL_ENV", "/from/env")

        assert get_venv() == "/venv"


class TestUnshareAvailability:
    @pytest.mark.parametrize("present", [("unshare",), ("slirp4netns",)])
    def test_both_tools_are_needed_before_trying_a_namespace(
        self, monkeypatch: pytest.MonkeyPatch, present: tuple[str, ...]
    ) -> None:
        run = MagicMock()
        monkeypatch.setattr(tools, "which_command", lambda name: name in present)
        monkeypatch.setattr(tools.subprocess, "run", run)

        assert unshare_user_namespace_available() is False
        run.assert_not_called()


def _os_release(monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> None:
    real_open = builtins.open

    def fake_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path) in files:
            return io.StringIO(files[str(path)])
        if str(path) in ("/etc/os-release", "/etc/lsb-release"):
            raise FileNotFoundError(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(builtins, "open", fake_open)


class TestSuggestPackageInstallation:
    @pytest.mark.parametrize(
        ("distro", "command"),
        [
            ("ubuntu", "sudo apt update && sudo apt install pkg"),
            ("debian", "sudo apt update && sudo apt install pkg"),
            ("fedora", "sudo dnf install pkg"),
            ("centos", "sudo yum install pkg"),
            ("rhel", "sudo yum install pkg"),
            ("arch", "sudo pacman -S pkg"),
        ],
    )
    @pytest.mark.parametrize("source", ["/etc/os-release", "/etc/lsb-release"])
    def test_the_command_follows_the_distribution(
        self, monkeypatch: pytest.MonkeyPatch, distro: str, command: str, source: str
    ) -> None:
        _os_release(monkeypatch, {source: f'NAME="x"\nID="{distro.upper()}"\n\n# comment without equal\n'})

        assert suggest_package_installation("pkg") == command

    @pytest.mark.parametrize("distro", ["plan9", "zorin", "nixos", "alpine"])
    def test_an_unknown_distribution_gets_the_list_of_package_managers(
        self, monkeypatch: pytest.MonkeyPatch, distro: str
    ) -> None:
        _os_release(monkeypatch, {"/etc/os-release": f"ID={distro}\n"})

        assert "common package managers" in suggest_package_installation("pkg")

    def test_without_any_release_file_the_list_of_package_managers_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _os_release(monkeypatch, {})

        assert "common package managers" in suggest_package_installation("pkg")


def _files(monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> None:
    real_open = builtins.open

    def fake_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path) in files:
            return io.StringIO(files[str(path)])
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


class TestDefaultInterface:
    def test_ip_route_is_run_with_its_output_captured_and_its_status_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = MagicMock(return_value=subprocess.CompletedProcess([], 0, stdout="default via 10.0.0.1 dev eth3 proto\n"))
        monkeypatch.setattr(tools.subprocess, "run", run)

        assert _get_default_interface_via_ip() == "eth3"

        assert run.call_args.args[0] == ["ip", "route"]
        assert run.call_args.kwargs["check"] is True
        assert run.call_args.kwargs["capture_output"] is True
        assert run.call_args.kwargs["text"] is True

    def test_the_default_destination_row_names_the_interface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        route = "Iface\tDestination\n\nlonely\neth1\t0001A8C0\neth0\t00000000\n"
        _files(monkeypatch, {"/proc/net/route": route})

        assert get_default_interface() == "eth0"


class TestResolvConf:
    @pytest.mark.skipif(sys.platform != "linux", reason="Only Linux reads its DNS servers from /etc/resolv.conf")
    def test_a_nameserver_line_without_an_address_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _files(monkeypatch, {"/etc/resolv.conf": "nameserver\nnameserver 1.1.1.1\nnameserver 2606:4700::1111\n"})

        ipv4, ipv6 = get_dns_servers()

        assert ipv4 == [ipaddress.ip_address("1.1.1.1")]
        assert ipv6 == [ipaddress.ip_address("2606:4700::1111")]

    @pytest.mark.parametrize("system", ["Darwin", "Windows"])
    @pytest.mark.parametrize(
        "helper",
        [
            get_dns_servers,
            get_bridge_interfaces,
            tools.get_systemd_resolved_static_dns,
            tools.get_systemd_resolved_upstream_dns,
        ],
    )
    def test_the_linux_readers_refuse_another_system(
        self, monkeypatch: pytest.MonkeyPatch, system: str, helper: Any
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: system)

        with pytest.raises(AssertionError):
            helper()

    def test_the_linux_readers_accept_the_real_system_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if platform.system() != "Linux":
            pytest.skip("Linux only")
        _files(monkeypatch, {"/etc/resolv.conf": "nameserver 9.9.9.9\n"})

        assert get_dns_servers()[0] == [ipaddress.ip_address("9.9.9.9")]
        assert isinstance(get_bridge_interfaces(), list)
        assert isinstance(tools.get_systemd_resolved_static_dns(), list)
        assert isinstance(tools.get_systemd_resolved_upstream_dns(), list)


class TestUpstreamDns:
    @pytest.mark.parametrize("system", ["Darwin", "Windows"])
    def test_another_system_gets_the_public_fallback(self, monkeypatch: pytest.MonkeyPatch, system: str) -> None:
        monkeypatch.setattr(platform, "system", lambda: system)
        monkeypatch.setattr(
            tools, "get_systemd_resolved_upstream_dns", lambda: pytest.fail("systemd-resolved is Linux only")
        )

        assert get_upstream_dns() == list(tools._FALLBACK_DNS)

    def test_linux_uses_systemd_resolved_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if platform.system() != "Linux":
            pytest.skip("Linux only")
        resolved = [ipaddress.ip_address("192.0.2.53")]
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: resolved)

        assert get_upstream_dns() == resolved

    def test_loopback_resolvers_are_dropped_even_when_they_are_not_the_systemd_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if platform.system() != "Linux":
            pytest.skip("Linux only")
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: [])
        _files(monkeypatch, {"/etc/resolv.conf": "nameserver 127.0.0.1\nnameserver ::1\nnameserver 9.9.9.9\n"})

        assert get_upstream_dns() == [ipaddress.ip_address("9.9.9.9")]
