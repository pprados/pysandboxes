# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The firejail command line built from a profile, and the path whitelist it relies on."""

import logging
import site
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import parse_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote.firejail_sse_daemon import AllowList, FireJailSSEDaemon, _follow_links
from pysandboxes.sb_types import ConfigLine

_CONFIG = ConfigLine("x", Path(), 1)


def _args(
    tmp_path: Path,
    rules: Any = EmptyRules,
    config: str | None = "restricted-network no\n",
    *,
    dns: list[Any] | None = None,
    bridges: list[str] | None = None,
    pipe_path: Path | None = None,
) -> list[str]:
    config_path = tmp_path / "firejail.config"
    if config is not None:
        config_path.write_text(config, encoding="utf-8")
    with (
        patch.object(firejail_sse_daemon, "FIREJAIL_CONFIG", config_path),
        patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"),
        patch.object(firejail_sse_daemon, "get_upstream_dns", return_value=dns or []),
        patch.object(
            firejail_sse_daemon, "get_bridge_interfaces", return_value=["br0"] if bridges is None else bridges
        ),
        patch.object(firejail_sse_daemon.threading, "Thread", return_value=Mock()),
    ):
        args, _ = FireJailSSEDaemon("token")._firejail_args(rules, {}, pipe_path, tmp_path)
    return list(args)


def _with_socket_rule() -> Any:
    socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
    return EmptyRules._replace(socket_rules=tuple(socket_rules))


class TestAllowList:
    def test_a_path_is_covered_by_itself_and_by_what_is_below_it(self) -> None:
        allowed = AllowList()
        allowed.add("/a")

        assert "/a" in allowed
        assert "/a/" in allowed
        assert "/a/b" in allowed
        assert "/ab" not in allowed
        assert "/" not in allowed
        assert list(allowed) == ["/a/"]

    def test_a_path_below_an_allowed_one_is_not_added(self) -> None:
        allowed = AllowList()
        allowed.add("/a/")
        allowed.add("/a/b")

        assert list(allowed) == ["/a/"]

    def test_a_parent_replaces_its_children_and_a_sibling_stays(self) -> None:
        allowed = AllowList()
        for path in ("/a/b/", "/a/c", "/ab"):
            allowed.add(path)

        allowed.add("/a")

        assert sorted(allowed) == ["/a/", "/ab/"]
        assert len(allowed) == 2

    def test_discarding_a_path_forgets_it(self) -> None:
        allowed = AllowList()
        allowed.add("/a")

        allowed.discard("/a")

        assert len(allowed) == 0
        assert "/a" not in allowed


class TestFollowLinks:
    def test_a_path_and_the_target_of_its_link_are_allowed(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target)
        allowed = AllowList()

        _follow_links(link, allowed)

        assert sorted(allowed) == sorted({str(tmp_path / "link") + "/", str(target.resolve()) + "/"})

    def test_the_system_libraries_are_left_out(self) -> None:
        allowed = AllowList()

        _follow_links(Path("/usr/lib/python3"), allowed)

        assert len(allowed) == 0

    def test_a_dangling_link_is_an_error(self, tmp_path: Path) -> None:
        link = tmp_path / "dangling"
        link.symlink_to(tmp_path / "missing")

        with pytest.raises(RuntimeError):
            _follow_links(link, AllowList())


@pytest.mark.parametrize(
    ("net", "host"),
    [(["--net=docker0"], "0.0.0.0"), (["--net=virbr0"], "0.0.0.0"), (["--net=none"], "127.0.0.1"), ([], "127.0.0.1")],
)
def test_the_sse_server_binds_every_interface_only_with_a_bridge(net: list[str], host: str) -> None:
    assert FireJailSSEDaemon("token")._sse_bind_host(["firejail", "--quiet", *net]) == host


def test_a_net_parameter_of_the_profile_is_parsed_and_the_others_are_kept() -> None:
    rules = [
        ConfigLine("firejail.net=docker0", Path(), 1),
        ConfigLine("firejail.seccomp=yes", Path(), 2),
        ConfigLine("firejail.rlimit-as=5m", Path(), 3),
        ConfigLine("something-else", Path(), 4),
    ]

    params, others = FireJailSSEDaemon("token").parse_rules(rules, [])

    assert dict(params) == {"net": "docker0", "seccomp": "yes", "rlimit-as": "5m"}
    assert [rule.rule for rule in others] == ["something-else"]


class TestFirejailArgs:
    def test_the_template_is_applied_and_a_profile_limit_replaces_its_default(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"rlimit-as": "5m"}))

        args = _args(tmp_path, rules)

        assert "--caps.drop=all" in args
        assert [arg for arg in args if arg.startswith("--rlimit-as=")] == ["--rlimit-as=5m"]

    @pytest.mark.parametrize(
        ("level", "quiet"), [(logging.WARNING, True), (logging.INFO, False), (logging.DEBUG, False)]
    )
    def test_firejail_is_quiet_unless_the_logger_reports_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: int, quiet: bool
    ) -> None:
        monkeypatch.setattr(firejail_sse_daemon.logger, "level", level)

        assert ("--quiet" in _args(tmp_path)) is quiet

    def test_the_python_directories_are_whitelisted_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        extra = tmp_path / "extra"
        extra.mkdir()
        packages = tmp_path / "packages"
        packages.mkdir()
        monkeypatch.setattr(sys, "path", [str(extra), str(tmp_path / "missing")])
        monkeypatch.setattr(site, "getsitepackages", lambda: [str(packages), str(tmp_path / "missing")])

        args = _args(tmp_path)

        for directory in (extra, packages):
            assert f"--whitelist={directory}/" in args
            assert f"--read-only={directory}/" in args
        assert not any(str(tmp_path / "missing") in arg for arg in args)

    def test_the_directories_of_the_interpreter_are_whitelisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        interpreter = tmp_path / "interpreter"
        interpreter.mkdir()
        monkeypatch.setattr(sys, "path", [])
        monkeypatch.setattr(site, "getsitepackages", lambda: [])
        monkeypatch.setattr(firejail_sse_daemon, "follow_links_executable", lambda executable, paths: {interpreter})

        args = _args(tmp_path)

        assert f"--whitelist={interpreter}/" in args
        assert f"--read-only={interpreter}/" in args

    def test_a_profile_parameter_replacing_a_template_line_keeps_the_following_lines(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"caps.drop": "none"}))

        args = _args(tmp_path, rules)

        assert "--caps.drop=all" not in args
        assert "--caps.drop=none" in args
        assert "--noprofile" in args
        assert "--noroot" in args

    def test_the_interpreter_is_whitelisted_read_only(self, tmp_path: Path) -> None:
        args = _args(tmp_path)

        assert any(
            arg.startswith("--whitelist=") and Path(sys.executable).resolve().parent.parent.as_posix() in arg
            for arg in args
        )

    def test_an_ignored_file_is_blacklisted(self, tmp_path: Path) -> None:
        args = _args(tmp_path, EmptyRules._replace(file_rules=(IgnoreRule(".env", _CONFIG),)))

        assert "--blacklist=.env" in args

    def test_the_pipe_directory_is_created_and_read_only(self, tmp_path: Path) -> None:
        pipe = tmp_path / "run" / "pipe"

        args = _args(tmp_path, pipe_path=pipe)

        assert f"--mkdir={pipe}" in args
        assert f"--read-only={pipe}" in args
        assert f"--whitelist={pipe.parent}/" in args

    def test_without_a_pipe_nothing_is_created(self, tmp_path: Path) -> None:
        assert not any(arg.startswith("--mkdir=") for arg in _args(tmp_path))

    def test_the_end_of_the_command_clears_the_environment(self, tmp_path: Path) -> None:
        from pysandboxes.sb_types import Envs

        args = _args(tmp_path, EmptyRules._replace(envs=Envs({"FOO": "bar"})))

        assert args[-3:] == ["/usr/bin/env", "-i", "FOO=bar"]

    def test_the_command_does_not_warn_about_root(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=firejail_sse_daemon.__name__):
            _args(tmp_path)

        assert "needs root" not in caplog.text


class TestExposedPaths:
    def _rules(self, *rules: FSExposeRule) -> Any:
        return EmptyRules._replace(file_rules=tuple(rules))

    def test_a_read_only_path_is_whitelisted_once_and_read_only(self, tmp_path: Path) -> None:
        args = _args(tmp_path, self._rules(FSExposeRule("/srv/data/", False, _CONFIG)))

        assert "--whitelist=/srv/data/" in args
        assert "--read-only=/srv/data/" in args
        assert "--read-write=/srv/data/" not in args

    def test_a_writable_path_is_read_write(self, tmp_path: Path) -> None:
        args = _args(tmp_path, self._rules(FSExposeRule("/srv/data/", True, _CONFIG)))

        assert "--whitelist=/srv/data/" in args
        assert "--read-write=/srv/data/" in args
        assert "--read-only=/srv/data/" not in args

    def test_a_writable_path_below_a_whitelisted_one_is_whitelisted_again_but_a_read_only_one_is_not(
        self, tmp_path: Path
    ) -> None:
        args = _args(
            tmp_path,
            self._rules(
                FSExposeRule("/srv/", False, _CONFIG),
                FSExposeRule("/srv/ro/", False, _CONFIG),
                FSExposeRule("/srv/rw/", True, _CONFIG),
            ),
        )

        assert "--whitelist=/srv/ro/" not in args
        assert "--read-only=/srv/ro/" in args
        assert "--whitelist=/srv/rw/" in args

    def test_a_path_sorting_before_etc_is_whitelisted(self, tmp_path: Path) -> None:
        args = _args(tmp_path, self._rules(FSExposeRule("/a/", False, _CONFIG)))

        assert "--whitelist=/a/" in args
        assert "--read-only=/a/" in args

    @pytest.mark.parametrize("path", ["/etc/", "/etc/ssl/", "/proc/", "/tmp/"])
    def test_the_paths_firejail_refuses_are_not_whitelisted(self, tmp_path: Path, path: str) -> None:
        args = _args(tmp_path, self._rules(FSExposeRule(path, False, _CONFIG)))

        assert f"--whitelist={path}" not in args

    def test_the_rules_are_returned_unchanged(self, tmp_path: Path) -> None:
        rules = _with_socket_rule()._replace(file_rules=(FSExposeRule("/srv/", False, _CONFIG),))
        config = tmp_path / "firejail.config"
        config.write_text("restricted-network no\n")
        with (
            patch.object(firejail_sse_daemon, "FIREJAIL_CONFIG", config),
            patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"),
            patch.object(firejail_sse_daemon, "get_upstream_dns", return_value=[]),
            patch.object(firejail_sse_daemon, "get_bridge_interfaces", return_value=["br0"]),
            patch.object(firejail_sse_daemon.threading, "Thread", return_value=Mock()),
        ):
            _, returned = FireJailSSEDaemon("token")._firejail_args(rules, {}, tmp_path / "pipe", tmp_path)

        assert returned.file_rules == rules.file_rules
        assert returned.socket_rules == rules.socket_rules


class TestNetwork:
    @pytest.mark.parametrize(
        ("config", "raises"),
        [
            ("# nothing about the network\n", True),
            ("restricted-network yes\nrestricted-network no\n", False),
        ],
    )
    def test_the_first_restricted_network_line_decides(self, tmp_path: Path, config: str, raises: bool) -> None:
        if raises:
            with pytest.raises(SandBoxError):
                _args(tmp_path, _with_socket_rule(), config, bridges=[])
        else:
            _args(tmp_path, _with_socket_rule(), config, bridges=[])

    def test_the_resolver_addresses_are_given_to_the_jail(self, tmp_path: Path) -> None:
        dns = [IPv4Address("8.8.8.8"), IPv4Address("127.0.0.1")]

        args = _args(tmp_path, _with_socket_rule(), dns=dns)

        assert [a for a in args if a.startswith("--dns=")] == ["--dns=8.8.8.8", "--dns=127.0.0.1"]

    @pytest.mark.parametrize("dns", [[], [IPv4Address("127.0.0.1")]])
    def test_loopback_only_resolvers_are_not_given_to_the_jail(self, tmp_path: Path, dns: list[Any]) -> None:
        args = _args(tmp_path, _with_socket_rule(), dns=dns)

        assert not any(a.startswith("--dns=") for a in args)

    @pytest.mark.parametrize(
        ("bridges", "chosen"),
        [(["br0", "docker0"], "docker0"), (["br0", "virbr0"], "br0"), (["docker0", "br0"], "docker0")],
    )
    def test_a_docker_bridge_is_preferred_else_the_first_one(
        self, tmp_path: Path, bridges: list[str], chosen: str
    ) -> None:
        assert f"--net={chosen}" in _args(tmp_path, _with_socket_rule(), bridges=bridges)

    def test_with_a_pipe_the_netfilter_files_are_given_to_firejail(self, tmp_path: Path) -> None:
        args = _args(tmp_path, _with_socket_rule(), pipe_path=tmp_path / "pipe")

        assert f"--netfilter={tmp_path / 'netfilter.net'}" in args
        assert f"--netfilter6={tmp_path / 'netfilter6.net'}" in args
        assert "--x11=none" in args

    def test_without_a_pipe_no_netfilter_file_is_given(self, tmp_path: Path) -> None:
        args = _args(tmp_path, _with_socket_rule())

        assert not any(a.startswith("--netfilter") for a in args)
