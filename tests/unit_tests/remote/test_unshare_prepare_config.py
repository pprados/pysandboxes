# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`UnshareSSEDaemon._prepare_unshare_config`: tools, DNS, hosts, mounts, ignore paths and sandbox envs."""

import builtins
import os
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import parse_rules as parse_file_rules
from pysandboxes.guard_socket import parse_rules as parse_socket_rules
from pysandboxes.remote import unshare_sse_daemon as usd
from pysandboxes.remote.slirp4netns_common import SLIRP_DNS
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon
from pysandboxes.sb_types import ConfigLine, Envs

_USERNS = "/proc/sys/kernel/unprivileged_userns_clone"


def _line(text: str) -> ConfigLine:
    return ConfigLine(text, Path(), 0)


def _rules(*, net: tuple[str, ...] = (), files: tuple[str, ...] = (), envs: dict[str, Any] | None = None) -> Any:
    sockets, _, _ = parse_socket_rules([_line(n) for n in net], [])
    file_rules, _ = parse_file_rules([_line(f) for f in files], [])
    return EmptyRules._replace(
        socket_rules=tuple(sockets), file_rules=tuple(file_rules), envs=Envs(envs or {})  # type: ignore[arg-type]
    )


def _prepare(
    rules: Any,
    tmp_path: Path,
    *,
    tools: tuple[str, ...] = ("unshare", "iptables"),
    dns: list[Any] | None = None,
    exists: set[str] | None = None,
    userns: str | None = None,
) -> Any:
    real_exists = os.path.exists
    real_open = builtins.open

    def fake_exists(path: Any) -> bool:
        if str(path) in ("/.dockerenv", "/run/.containerenv"):
            return str(path) in (exists or set())
        return real_exists(path)

    def fake_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path) == _USERNS:
            if userns is None:
                raise FileNotFoundError(path)
            fake = tmp_path / "userns"
            fake.write_text(userns)
            return real_open(fake, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    with (
        patch.object(usd, "which_command", side_effect=lambda name: name if name in tools else None),
        patch.object(usd, "get_upstream_dns", return_value=dns or []),
        patch.object(usd.os.path, "exists", side_effect=fake_exists),
        patch.object(builtins, "open", side_effect=fake_open),
    ):
        daemon = UnshareSSEDaemon("tok")
        try:
            return daemon._prepare_unshare_config(rules, tmp_path / "pipe", "/chroot")
        finally:
            daemon._remove_chroot_dirs()


class TestRequirements:
    @pytest.mark.parametrize("missing", ["unshare", "iptables"])
    def test_a_missing_tool_is_an_error_naming_it(self, tmp_path: Path, missing: str) -> None:
        tools = tuple(t for t in ("unshare", "iptables") if t != missing)

        with pytest.raises(SandBoxError, match=f"^{missing} not found.$"):
            _prepare(_rules(), tmp_path, tools=tools)

    @pytest.mark.parametrize("value", ["0", "", "10"])
    def test_a_kernel_without_unprivileged_namespaces_is_refused(self, tmp_path: Path, value: str) -> None:
        with pytest.raises(RuntimeError, match="unprivileged_userns_clone must be 1"):
            _prepare(_rules(), tmp_path, userns=value)

    @pytest.mark.parametrize("value", ["1", "1\n"])
    def test_a_kernel_with_unprivileged_namespaces_is_accepted(self, tmp_path: Path, value: str) -> None:
        config, _ = _prepare(_rules(), tmp_path, userns=value)

        assert config.chroot_dir == "/chroot"

    def test_a_kernel_without_the_switch_is_accepted(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path, userns=None)

        assert config.named_pipe == str(tmp_path / "pipe")


class TestDns:
    def test_without_upstream_only_the_slirp_resolver_is_used(self, tmp_path: Path) -> None:
        config, dns = _prepare(_rules(), tmp_path)

        assert dns == [IPv4Address(SLIRP_DNS)]
        assert config.dns_servers == [SLIRP_DNS]

    def test_the_first_upstream_follows_the_slirp_resolver(self, tmp_path: Path) -> None:
        upstream = [IPv4Address("9.9.9.9"), IPv4Address("8.8.8.8")]

        config, dns = _prepare(_rules(), tmp_path, dns=upstream)

        assert config.dns_servers == [SLIRP_DNS, "9.9.9.9"]
        assert dns == [IPv4Address(SLIRP_DNS), IPv4Address("9.9.9.9")]

    def test_the_slirp_resolver_is_not_repeated_among_the_upstream(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path, dns=[IPv4Address(SLIRP_DNS), IPv4Address("9.9.9.9")])

        assert config.dns_servers == [SLIRP_DNS, "9.9.9.9"]

    def test_an_upstream_server_above_the_slirp_resolver_is_kept(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path, dns=[IPv4Address(SLIRP_DNS), IPv4Address("10.9.9.9")])

        assert config.dns_servers == [SLIRP_DNS, "10.9.9.9"]

    def test_only_ipv4_upstream_servers_count(self, tmp_path: Path) -> None:
        from ipaddress import IPv6Address

        config, _ = _prepare(_rules(), tmp_path, dns=[IPv6Address("::1")])

        assert config.dns_servers == [SLIRP_DNS]

    @pytest.mark.parametrize("marker", ["/.dockerenv", "/run/.containerenv"])
    def test_in_a_container_the_upstream_servers_are_ignored(self, tmp_path: Path, marker: str) -> None:
        config, _ = _prepare(_rules(), tmp_path, dns=[IPv4Address("9.9.9.9")], exists={marker})

        assert config.dns_servers == [SLIRP_DNS]

    def test_the_resolvers_are_allowed_in_the_netfilter_rules(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path, dns=[IPv4Address("9.9.9.9")])

        assert any(SLIRP_DNS in rule for rule in config.netfilter_rules)
        assert any("9.9.9.9" in rule for rule in config.netfilter_rules)


class TestHosts:
    def test_an_allowed_outgoing_host_name_is_pinned_to_its_address(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(net=("net=ALLOW|TCP|localhost|443|OUT",)), tmp_path)

        assert config.hosts == ["127.0.0.1 localhost"]

    def test_the_hosts_are_sorted_and_unique(self, tmp_path: Path) -> None:
        net = ("net=ALLOW|TCP|localhost|443|OUT", "net=ALLOW|TCP|localhost|80|OUT")

        config, _ = _prepare(_rules(net=net), tmp_path)

        assert config.hosts == ["127.0.0.1 localhost"]

    @pytest.mark.parametrize(
        "skipped",
        [
            "net=DENY|TCP|1.1.1.1|443|OUT",
            "net=ALLOW|TCP|1.1.1.1|443|IN",
            "net=ALLOW|TCP|10.0.0.0/8|443|OUT",
            "net=ALLOW|TCP|1.2.3.4|443|OUT",
        ],
    )
    def test_a_skipped_rule_does_not_hide_the_host_that_follows(self, tmp_path: Path, skipped: str) -> None:
        config, _ = _prepare(_rules(net=(skipped, "net=ALLOW|TCP|localhost|443|OUT")), tmp_path)

        assert config.hosts == ["127.0.0.1 localhost"]

    @pytest.mark.parametrize(
        "rule",
        [
            "net=DENY|TCP|localhost|443|OUT",
            "net=ALLOW|TCP|localhost|443|IN",
            "net=ALLOW|TCP|10.0.0.0/8|443|OUT",
            "net=ALLOW|TCP|1.2.3.4|443|OUT",
        ],
    )
    def test_other_rules_pin_no_host(self, tmp_path: Path, rule: str) -> None:
        config, _ = _prepare(_rules(net=(rule,)), tmp_path)

        assert config.hosts == []


class TestMounts:
    def test_the_system_directories_are_read_only_and_the_pipe_is_writable(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path)

        pipe = str(tmp_path / "pipe")
        for path in ("/bin", "/usr", "/lib", "/lib64", "/etc"):
            if os.path.exists(path):
                assert (path, path) in config.mounts_ro
        assert config.mounts_rw == [(pipe, pipe)]
        assert (pipe, pipe) not in config.mounts_ro

    def test_the_interpreter_and_its_search_path_are_mounted(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path)

        assert (sys.executable, sys.executable) in config.mounts_ro
        for entry in sys.path:
            if entry and os.path.exists(entry):
                assert (entry, entry) in config.mounts_ro

    def test_a_missing_search_path_entry_is_not_mounted(self, tmp_path: Path) -> None:
        ghost = str(tmp_path / "ghost")
        with patch.object(sys, "path", [ghost]):
            config, _ = _prepare(_rules(), tmp_path)

        assert (ghost, ghost) not in config.mounts_ro

    def test_the_site_packages_are_mounted(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        with patch.object(usd.site, "getsitepackages", return_value=[str(site_dir)]), patch.object(sys, "path", []):
            config, _ = _prepare(_rules(), tmp_path)

        assert (str(site_dir), str(site_dir)) in config.mounts_ro

    def test_a_python_without_site_packages_support_is_tolerated(self, tmp_path: Path) -> None:
        with patch.object(usd, "site", object()), patch.object(sys, "path", []):
            config, _ = _prepare(_rules(), tmp_path)

        assert (sys.executable, sys.executable) in config.mounts_ro

    def test_every_directory_of_the_interpreter_chain_is_mounted(self, tmp_path: Path) -> None:
        link = tmp_path / "chain"
        with patch.object(usd, "follow_links_executable", return_value={link}):
            config, _ = _prepare(_rules(), tmp_path)

        assert (str(link), str(link)) in config.mounts_ro

    def test_an_exposed_path_is_mounted_read_only_or_writable(self, tmp_path: Path) -> None:
        ro, rw = tmp_path / "ro", tmp_path / "rw"
        ro.mkdir()
        rw.mkdir()

        config, _ = _prepare(_rules(files=(f"expose-ro={ro}", f"expose-rw={rw}")), tmp_path)

        ro_mount, rw_mount = f"{ro}/", f"{rw}/"
        assert (ro_mount, ro_mount) in config.mounts_ro
        assert (rw_mount, rw_mount) in config.mounts_rw
        assert (rw_mount, rw_mount) not in config.mounts_ro
        assert (ro_mount, ro_mount) not in config.mounts_rw


class TestIgnoreAndEnvs:
    def test_ignore_rules_resolve_under_the_working_directory(self, tmp_path: Path, monkeypatch: Any) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "secret.key").write_text("x")
        (tmp_path / "plain.txt").write_text("x")
        monkeypatch.chdir(tmp_path)

        config, _ = _prepare(_rules(files=("ignore=*.key",)), tmp_path)

        assert config.current_dir == os.getcwd()
        assert config.ignore_paths == [str(Path("sub") / "secret.key")]

    def test_without_ignore_rules_nothing_is_ignored(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path)

        assert config.ignore_paths == []

    def test_the_sandbox_environment_is_stringified_and_none_becomes_empty(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(envs={"A": "1", "B": None, "C": 3}), tmp_path)

        assert config.sandbox_envs == {"A": "1", "B": "", "C": "3"}

    def test_the_pipe_and_chroot_are_forwarded(self, tmp_path: Path) -> None:
        config, _ = _prepare(_rules(), tmp_path)

        assert config.named_pipe == str(tmp_path / "pipe")
        assert config.chroot_dir == "/chroot"
