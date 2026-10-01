# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Additional coverage for pysandboxes.remote.tools.

Targets the parent-process-only surface left uncovered by test_tools.py and
test_restricted_unpickle.py: OS/network introspection helpers, the pickle
prescan budgets, the restricted unpickler's find_class error paths, and the
descriptor rebuild fallback. ``set_pdeathsig`` is out of scope: its only call
sites (``main_sandbox.py``'s ``__main__`` block and the ``preexec_fn`` in
``slirp4netns_common.py``) run inside the sandboxed child, never in the
parent process a unit test occupies.
"""

import base64
import ipaddress
import pickle
import subprocess
import sys
import types
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Any
from unittest.mock import Mock, mock_open, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RestrictedUnpicklingError, SandBoxProtocolError
from pysandboxes.remote import tools
from pysandboxes.remote.tools import (
    _FALLBACK_DNS,
    _get_default_interface_via_ip,
    _prescan,
    from_b85_restricted,
    get_bridge_interfaces,
    get_default_interface,
    get_dns_servers,
    get_systemd_resolved_static_dns,
    get_systemd_resolved_upstream_dns,
    get_upstream_dns,
    rebuild_from_descriptor,
    result_predicate,
    suggest_package_installation,
    unshare_user_namespace_available,
)


def _stack_global_bytes(module: str, qualname: str) -> bytes:
    """Minimal protocol-5 pickle bytes resolving (module, qualname) via STACK_GLOBAL."""

    def _short_unicode(value: str) -> bytes:
        encoded = value.encode("utf-8")
        return b"\x8c" + bytes([len(encoded)]) + encoded

    return b"\x80\x05" + _short_unicode(module) + _short_unicode(qualname) + b"\x93."


class TestUnshareUserNamespaceAvailable:
    """Missing-command and exception paths (lines 101, 110-111)."""

    def test_missing_command_returns_false_without_running_unshare(self) -> None:
        """A missing `unshare` or `slirp4netns` binary short-circuits before any subprocess call."""
        with patch("pysandboxes.remote.tools.which_command", return_value=None):
            with patch("pysandboxes.remote.tools.subprocess.run") as mock_run:
                assert unshare_user_namespace_available() is False
                mock_run.assert_not_called()

    def test_timeout_returns_false(self) -> None:
        """A probe that times out is treated as user namespaces being unavailable."""
        with patch("pysandboxes.remote.tools.which_command", return_value=Path("/usr/bin/unshare")):
            with patch(
                "pysandboxes.remote.tools.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["unshare"], timeout=5),
            ) as mock_run:
                assert unshare_user_namespace_available() is False
                mock_run.assert_called_once()


class TestSuggestPackageInstallationExtraBranches:
    """Distro/OS branches test_tools.py does not exercise (215-219, 228, 232, 252)."""

    def test_falls_back_to_lsb_release_when_os_release_missing(self) -> None:
        """A missing /etc/os-release falls back to /etc/lsb-release."""
        lsb_content = mock_open(read_data='ID="ubuntu"\n').return_value
        with patch("sys.platform", "linux"):
            with patch("builtins.open", side_effect=[FileNotFoundError(), lsb_content]):
                result = suggest_package_installation("firejail")
        assert "apt install firejail" in result

    def test_fedora(self) -> None:
        """Fedora suggests dnf."""
        with patch("sys.platform", "linux"):
            with patch("builtins.open", mock_open(read_data='ID="fedora"\n')):
                result = suggest_package_installation("firejail")
        assert "dnf install firejail" in result

    def test_arch(self) -> None:
        """Arch Linux suggests pacman."""
        with patch("sys.platform", "linux"):
            with patch("builtins.open", mock_open(read_data='ID="arch"\n')):
                result = suggest_package_installation("firejail")
        assert "pacman -S firejail" in result

    def test_windows(self) -> None:
        """Windows suggests winget."""
        with patch("sys.platform", "win32"):
            result = suggest_package_installation("firejail")
        assert "winget install firejail" in result


class TestPrescanBudgets:
    """Opcode/mark/memo budgets and the unparsable-stream path (584, 591, 597, 600-602)."""

    def test_opcode_budget_exceeded(self) -> None:
        """A stream with more opcodes than the (patched, tiny) budget is refused."""
        with patch("pysandboxes.remote.tools._MAX_OPCODES", 0):
            with pytest.raises(RestrictedUnpicklingError, match="opcode transport budget"):
                _prescan(pickle.dumps({"a": 1}, protocol=5))

    def test_mark_depth_budget_exceeded(self) -> None:
        """A MARK opcode beyond the (patched, tiny) depth budget is refused."""
        with patch("pysandboxes.remote.tools._MAX_MARK_DEPTH", 0):
            with pytest.raises(RestrictedUnpicklingError, match="MARK budget"):
                _prescan(pickle.dumps((1, 2, 3, 4), protocol=5))

    def test_memo_budget_exceeded(self) -> None:
        """A memoized object beyond the (patched, tiny) memo budget is refused."""
        with patch("pysandboxes.remote.tools._MAX_MEMO", 0):
            with pytest.raises(RestrictedUnpicklingError, match="memo budget"):
                _prescan(pickle.dumps([1, 2, 3], protocol=5))

    def test_unparsable_stream_is_refused(self) -> None:
        """A stream `pickletools.genops` cannot parse is refused, not left to crash."""
        with pytest.raises(RestrictedUnpicklingError, match="unparsable pickle stream"):
            _prescan(b"not a pickle stream at all")


class TestFindClassErrorPaths:
    """Module-not-loaded and dotted-attribute failures (639, 649-650)."""

    def test_module_not_loaded_is_refused(self) -> None:
        """A global referencing a module the parent never imported is refused."""
        data = _stack_global_bytes("no_such_module_pysandboxes_xyz", "Foo")
        with pytest.raises(RestrictedUnpicklingError, match="not loaded"):
            from_b85_restricted(base64.b85encode(data).decode(), result_predicate)

    def test_dotted_attribute_resolution_failure_is_refused(self) -> None:
        """A global naming an attribute that does not exist on a loaded module is refused."""
        data = _stack_global_bytes("sys", "no_such_attribute_xyz")
        with pytest.raises(RestrictedUnpicklingError, match="could not be resolved"):
            from_b85_restricted(base64.b85encode(data).decode(), result_predicate)


def test_result_predicate_denies_a_denylisted_builtin() -> None:
    """The builtins.eval branch of the denylist (line 685)."""
    assert result_predicate("builtins", "eval", eval) is False


class _StrictError(Exception):
    """Exception whose __new__ demands the constructor arguments it never gets."""

    new_calls = 0

    def __new__(cls, *args: object) -> "_StrictError":
        _StrictError.new_calls += 1
        if not args:
            raise TypeError("_StrictError requires at least one positional argument")
        return super().__new__(cls, *args)


def test_rebuild_from_descriptor_falls_back_when_new_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolvable class whose __new__ fails still reaches the fallback (756-759)."""
    # Registered under a module of its own: activating the import guard evicts this test
    # module from sys.modules, the only place rebuild_from_descriptor looks.
    holder = types.ModuleType("strict_error_holder")
    holder._StrictError = _StrictError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "strict_error_holder", holder)
    _StrictError.new_calls = 0
    descriptor: tuple[str, str, str, list[str]] = ("strict_error_holder", "_StrictError", "boom", [])

    rebuilt = rebuild_from_descriptor(descriptor, SandBoxProtocolError)

    assert _StrictError.new_calls == 1, "the failing __new__ must have actually run"
    assert type(rebuilt) is SandBoxProtocolError
    assert "strict_error_holder._StrictError: boom" in str(rebuilt)


class TestGetDefaultInterfaceViaIp:
    """subprocess-based interface lookup and its exception paths (823-824, 829-844)."""

    def test_match_found(self) -> None:
        """`ip route` output with a default route yields its interface name."""
        stdout = "default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.100\n"
        with patch(
            "pysandboxes.remote.tools.subprocess.run",
            return_value=Mock(stdout=stdout),
        ):
            assert _get_default_interface_via_ip() == "eth0"

    def test_no_default_route_returns_none(self) -> None:
        """`ip route` output without a default route yields None."""
        with patch(
            "pysandboxes.remote.tools.subprocess.run",
            return_value=Mock(stdout="10.0.0.0/24 dev eth0 scope link\n"),
        ):
            assert _get_default_interface_via_ip() is None

    def test_command_not_found(self, caplog: pytest.LogCaptureFixture) -> None:
        """A missing `ip` binary is logged and yields None."""
        caplog.set_level("WARNING", logger="pysandboxes.remote.tools")
        with patch("pysandboxes.remote.tools.subprocess.run", side_effect=FileNotFoundError):
            assert _get_default_interface_via_ip() is None
        assert "iproute2" in caplog.text

    def test_called_process_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """A non-zero `ip route` exit is logged and yields None."""
        caplog.set_level("WARNING", logger="pysandboxes.remote.tools")
        error = subprocess.CalledProcessError(1, ["ip", "route"], stderr="boom")
        with patch("pysandboxes.remote.tools.subprocess.run", side_effect=error):
            assert _get_default_interface_via_ip() is None
        assert "Error executing 'ip route'" in caplog.text

    def test_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        """A timed-out `ip route` call is logged and yields None."""
        caplog.set_level("WARNING", logger="pysandboxes.remote.tools")
        with patch(
            "pysandboxes.remote.tools.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ip", "route"], timeout=5),
        ):
            assert _get_default_interface_via_ip() is None
        assert "timed out" in caplog.text

    def test_unexpected_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """Any other unexpected error is logged and yields None."""
        caplog.set_level("WARNING", logger="pysandboxes.remote.tools")
        with patch("pysandboxes.remote.tools.subprocess.run", side_effect=RuntimeError("boom")):
            assert _get_default_interface_via_ip() is None
        assert "unexpected error occurred" in caplog.text


class TestGetDefaultInterface:
    """/proc/net/route parsing and the fallback to `ip route` (866-877)."""

    def test_default_route_found_in_proc(self) -> None:
        """A `00000000` destination row in /proc/net/route names the default interface."""
        content = "Iface\tDestination\tGateway\n" "eth0\t00000000\t0101A8C0\n"
        with patch("builtins.open", mock_open(read_data=content)):
            with patch("pysandboxes.remote.tools._get_default_interface_via_ip") as via_ip:
                assert get_default_interface() == "eth0"
                via_ip.assert_not_called()

    def test_no_default_route_falls_back_to_ip_route(self) -> None:
        """No default row in /proc/net/route falls back to `ip route`."""
        content = "Iface\tDestination\tGateway\n" "eth0\t0100A8C0\t0101A8C0\n"
        with patch("builtins.open", mock_open(read_data=content)):
            with patch("pysandboxes.remote.tools._get_default_interface_via_ip", return_value="wlan0") as via_ip:
                assert get_default_interface() == "wlan0"
                via_ip.assert_called_once()

    def test_missing_proc_file_returns_none_without_fallback(self) -> None:
        """A missing /proc/net/route returns None without falling back to `ip route`."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch("pysandboxes.remote.tools._get_default_interface_via_ip") as via_ip:
                assert get_default_interface() is None
                via_ip.assert_not_called()


class _FakeBridgeDir:
    """Stand-in for the `<iface>/bridge` marker directory."""

    def __init__(self, has_bridge: bool) -> None:
        self._has_bridge = has_bridge

    def is_dir(self) -> bool:
        """Whether the bridge marker directory exists."""
        return self._has_bridge


class _FakeInterfaceDir:
    """Stand-in for one `/sys/class/net/<iface>` entry."""

    def __init__(self, name: str, has_bridge: bool) -> None:
        self.name = name
        self._has_bridge = has_bridge

    def is_dir(self) -> bool:
        """Every fake interface entry is a directory."""
        return True

    def __truediv__(self, _other: str) -> _FakeBridgeDir:
        """Support `interface_dir / "bridge"`."""
        return _FakeBridgeDir(self._has_bridge)


class _FakeNetPath:
    """Stand-in for `Path("/sys/class/net")`, without touching the real filesystem."""

    def __init__(self, interfaces: list[_FakeInterfaceDir] | None = None, is_dir_result: bool = True) -> None:
        self._interfaces = interfaces or []
        self._is_dir_result = is_dir_result

    def is_dir(self) -> bool:
        """Whether the fake sysfs path exists as a directory."""
        return self._is_dir_result

    def iterdir(self) -> Any:
        """Yield the fake interface entries."""
        return iter(self._interfaces)


class _RaisingNetPath(_FakeNetPath):
    """A fake net path whose `iterdir` raises, to exercise the error paths."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self._exc = exc

    def iterdir(self) -> Any:
        """Raise the configured exception instead of yielding entries."""
        raise self._exc


class TestGetBridgeInterfaces:
    """Bridge detection via /sys/class/net and its error paths (894-925)."""

    def _fake_path(self, fake: _FakeNetPath) -> Any:
        """Build a `Path` replacement that returns `fake` only for /sys/class/net."""
        return lambda p: fake if p == "/sys/class/net" else Path(p)

    def test_finds_bridge_interfaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the interface with a `bridge` marker directory is reported."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        fake = _FakeNetPath([_FakeInterfaceDir("eth0", False), _FakeInterfaceDir("br0", True)])
        monkeypatch.setattr(tools, "Path", self._fake_path(fake))
        assert get_bridge_interfaces() == ["br0"]

    def test_missing_sysfs_path_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing /sys/class/net returns an empty list instead of raising."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        fake = _FakeNetPath(is_dir_result=False)
        monkeypatch.setattr(tools, "Path", self._fake_path(fake))
        assert get_bridge_interfaces() == []

    def test_permission_error_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PermissionError while iterating interfaces is re-raised as RuntimeError."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        fake = _RaisingNetPath(PermissionError("denied"))
        monkeypatch.setattr(tools, "Path", self._fake_path(fake))
        with pytest.raises(RuntimeError, match="Insufficient permissions"):
            get_bridge_interfaces()

    def test_unexpected_error_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any other error while iterating interfaces is re-raised as RuntimeError."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        fake = _RaisingNetPath(RuntimeError("boom"))
        monkeypatch.setattr(tools, "Path", self._fake_path(fake))
        with pytest.raises(RuntimeError, match="unexpected error occurred"):
            get_bridge_interfaces()


class TestGetDnsServers:
    """/etc/resolv.conf parsing, split by address family (938-975)."""

    def test_parses_ipv4_and_ipv6(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mixed IPv4/IPv6 nameserver lines are split into their own lists."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        content = "nameserver 8.8.8.8\nnameserver 2001:4860:4860::8888\n# comment\n"
        with patch("builtins.open", mock_open(read_data=content)):
            ipv4_list, ipv6_list = get_dns_servers()
        assert ipv4_list == [ipaddress.ip_address("8.8.8.8")]
        assert ipv6_list == [ipaddress.ip_address("2001:4860:4860::8888")]


class TestGetSystemdResolvedStaticDns:
    """resolv.conf-style parsing and its error paths (991-1026)."""

    def test_parses_static_dns_from_primary_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The primary path's resolv.conf-style 'nameserver' lines are parsed."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools.os.path, "exists", lambda path: path == "/run/systemd/resolve/resolv.conf")
        with patch("builtins.open", mock_open(read_data="nameserver 8.8.8.8\n")):
            result = get_systemd_resolved_static_dns()
        assert set(result) == {ipaddress.ip_address("8.8.8.8")}

    def test_neither_config_file_exists_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither config path existing returns an empty list."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools.os.path, "exists", lambda path: False)
        assert get_systemd_resolved_static_dns() == []

    def test_io_error_is_reported_and_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """An IOError opening the config file is printed and swallowed."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools.os.path, "exists", lambda path: path == "/run/systemd/resolve/resolv.conf")
        with patch("builtins.open", side_effect=IOError("boom")):
            result = get_systemd_resolved_static_dns()
        assert result == []
        assert "Error reading" in capsys.readouterr().out

    def test_unexpected_error_is_reported_and_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A malformed IP address is printed and swallowed, not left to propagate."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools.os.path, "exists", lambda path: path == "/run/systemd/resolve/resolv.conf")
        # A malformed IP makes ipaddress.ip_address raise ValueError, not IOError.
        with patch("builtins.open", mock_open(read_data="nameserver not-an-ip\n")):
            result = get_systemd_resolved_static_dns()
        assert result == []
        assert "unexpected error occurred" in capsys.readouterr().out

    def test_fallback_config_path_parses_dns_directive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The resolved.conf fallback reads 'DNS=', drops suffixes, and skips 'FallbackDNS='."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools.os.path, "exists", lambda path: path == "/etc/systemd/resolved.conf")
        content = "[Resolve]\n#DNS=9.9.9.9\nDNS=1.1.1.1#cloudflare-dns.com 10.0.0.1%eth0\nFallbackDNS=8.8.8.8\n"
        with patch("builtins.open", mock_open(read_data=content)):
            result = get_systemd_resolved_static_dns()
        assert set(result) == {ipaddress.ip_address("1.1.1.1"), ipaddress.ip_address("10.0.0.1")}


class TestGetSystemdResolvedUpstreamDns:
    """Static-first, then `resolvectl`, then its error paths (1043-1082)."""

    def test_uses_static_result_without_calling_resolvectl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The static config wins, so `resolvectl` never runs."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        static = [ipaddress.ip_address("9.9.9.9")]
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: static)
        with patch("pysandboxes.remote.tools.subprocess.run") as mock_run:
            assert get_systemd_resolved_upstream_dns() == static
            mock_run.assert_not_called()

    def test_resolvectl_missing_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No `resolvectl` binary on the host returns an empty list."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        with patch("pysandboxes.remote.tools.shutil.which", return_value=None):
            assert get_systemd_resolved_upstream_dns() == []

    def test_resolvectl_output_is_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A real `resolvectl status` output is parsed into addresses."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        stdout = "Global\n         DNS Servers: 8.8.8.8 1.1.1.1\n"
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch("pysandboxes.remote.tools.subprocess.run", return_value=Mock(stdout=stdout)):
                result = get_systemd_resolved_upstream_dns()
        assert set(result) == {ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("1.1.1.1")}

    def test_resolvectl_singular_current_dns_server_is_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`resolvectl status` also reports a singular 'Current DNS Server' line."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        stdout = "Link 2 (eth0)\n    Current DNS Server: 192.168.1.1\n"
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch("pysandboxes.remote.tools.subprocess.run", return_value=Mock(stdout=stdout)):
                result = get_systemd_resolved_upstream_dns()
        assert set(result) == {ipaddress.ip_address("192.168.1.1")}

    def test_resolvectl_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing `resolvectl` binary at run time returns an empty list."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch("pysandboxes.remote.tools.subprocess.run", side_effect=FileNotFoundError) as mock_run:
                assert get_systemd_resolved_upstream_dns() == []
                mock_run.assert_called_once()

    def test_resolvectl_called_process_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-zero `resolvectl` exit is logged at debug level and swallowed."""
        caplog.set_level("DEBUG", logger="pysandboxes.remote.tools")
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        error = subprocess.CalledProcessError(1, ["resolvectl", "status"], stderr="boom")
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch("pysandboxes.remote.tools.subprocess.run", side_effect=error):
                assert get_systemd_resolved_upstream_dns() == []
        assert "Error executing 'resolvectl status'" in caplog.text

    def test_resolvectl_timeout(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A `resolvectl` timeout is logged at debug level and swallowed."""
        caplog.set_level("DEBUG", logger="pysandboxes.remote.tools")
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch(
                "pysandboxes.remote.tools.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["resolvectl", "status"], timeout=5),
            ):
                assert get_systemd_resolved_upstream_dns() == []
        assert "timed out" in caplog.text

    def test_resolvectl_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unexpected error running `resolvectl` is logged and swallowed."""
        caplog.set_level("DEBUG", logger="pysandboxes.remote.tools")
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_static_dns", lambda: [])
        with patch("pysandboxes.remote.tools.shutil.which", return_value="/usr/bin/resolvectl"):
            with patch("pysandboxes.remote.tools.subprocess.run", side_effect=RuntimeError("boom")):
                assert get_systemd_resolved_upstream_dns() == []
        assert "Unexpected error during resolvectl execution" in caplog.text


class TestGetUpstreamDns:
    """The three-strategy orchestration and its exception handling (1109-1132)."""

    def test_non_linux_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Off Linux, the function skips straight to the public DNS fallback."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Darwin")
        assert get_upstream_dns() == _FALLBACK_DNS

    def test_systemd_result_is_used_without_reading_resolv_conf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-empty systemd-resolved result short-circuits strategy 2."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        wanted: list[IPv4Address | IPv6Address] = [ipaddress.ip_address("9.9.9.9")]
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: wanted)
        with patch("pysandboxes.remote.tools.get_dns_servers") as mock_get_dns:
            assert get_upstream_dns() == wanted
            mock_get_dns.assert_not_called()

    def test_falls_back_to_resolv_conf_and_filters_stub_resolvers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """/etc/resolv.conf is tried next, and the systemd-resolved stub IP is filtered out."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: [])
        real = ipaddress.ip_address("4.4.4.4")
        stub = ipaddress.ip_address("127.0.0.53")
        monkeypatch.setattr(tools, "get_dns_servers", lambda: ([real, stub], []))
        assert get_upstream_dns() == [real]

    def test_falls_back_to_public_dns_when_everything_else_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both prior strategies find nothing, the public DNS fallback is used."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: [])
        monkeypatch.setattr(tools, "get_dns_servers", lambda: ([], []))
        assert get_upstream_dns() == _FALLBACK_DNS

    def test_assertion_error_from_get_dns_servers_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An AssertionError out of strategy 2 is caught, not left to propagate."""
        monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
        monkeypatch.setattr(tools, "get_systemd_resolved_upstream_dns", lambda: [])

        def _raise() -> Any:
            """Simulate strategy 2 raising instead of returning."""
            raise AssertionError("not linux after all")

        monkeypatch.setattr(tools, "get_dns_servers", _raise)
        assert get_upstream_dns() == _FALLBACK_DNS
