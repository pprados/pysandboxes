# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The bwrap command line built from a profile, and the ignore-mask helpers it relies on."""

import os
import site
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import parse_rules
from pysandboxes.remote import bwrap_sse_daemon
from pysandboxes.remote.bwrap_sse_daemon import (
    BWrapSSEDaemon,
    _ignore_mask_targets,
    _is_inside_exposed,
    _is_reachable_in_sandbox,
    _resolve_ignore_paths,
)
from pysandboxes.sb_types import ConfigLine, Envs

_CONFIG = ConfigLine("x", Path(), 1)


def _args(tmp_path: Path, rules: Any = EmptyRules) -> list[str]:
    with patch.object(bwrap_sse_daemon, "which_command", return_value="/usr/bin/bwrap"):
        return list(BWrapSSEDaemon("token")._bwrap_args(rules, {}, tmp_path / "pipe", tmp_path))


def _triples(args: list[str], option: str) -> list[tuple[str, str]]:
    return [(args[i + 1], args[i + 2]) for i, arg in enumerate(args) if arg == option and i + 2 < len(args)]


def _setenv(args: list[str], name: str) -> str | None:
    for src, value in _triples(args, "--setenv"):
        if src == name:
            return value
    return None


class TestBwrapArgs:
    def test_the_template_comes_first_and_names_the_interpreter(self, tmp_path: Path) -> None:
        args = _args(tmp_path)

        assert args[0] == "/usr/bin/bwrap"
        assert "--die-with-parent" in args
        assert "--clearenv" in args
        assert args[args.index("--argv0") + 1] == str(Path(sys.executable).resolve())

    def test_the_profile_environment_is_set_in_the_child(self, tmp_path: Path) -> None:
        args = _args(tmp_path, EmptyRules._replace(envs=Envs({"FOO": "bar", "N": "1"})))

        assert _setenv(args, "FOO") == "bar"
        assert _setenv(args, "N") == "1"

    def test_the_profile_network_parameters_are_added_but_not_the_share_ones(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(os_sandbox_params={"share-net": "", "with-value": "1", "bare": ""})  # type: ignore[arg-type]

        args = _args(tmp_path, rules)

        assert "--with-value=1" in args
        assert "--bare" in args
        assert "--share-net=" not in args
        assert "--share-net" not in args[args.index("--bare") - 3 :]

    def test_the_run_path_of_the_resolver_is_bound_when_it_exists(self, tmp_path: Path) -> None:
        with patch.object(bwrap_sse_daemon, "_dns_run_paths", return_value=["/run/systemd/resolve/stub-resolv.conf"]):
            binds = _triples(_args(tmp_path), "--ro-bind-try")

        assert binds == [("/run/systemd/resolve/stub-resolv.conf", "/run/systemd/resolve/stub-resolv.conf")]

    def test_the_system_directories_are_bound_read_only(self, tmp_path: Path) -> None:
        binds = _triples(_args(tmp_path), "--ro-bind")

        assert ("/usr", "/usr") in binds
        assert ("/etc", "/etc") in binds
        for lib in ("/lib", "/lib64"):
            assert ((lib, lib) in binds) is Path(lib).is_dir()

    def test_each_existing_python_path_directory_is_bound_and_the_others_are_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        packages = tmp_path / "packages"
        packages.mkdir()
        monkeypatch.setattr(sys, "path", ["", str(tmp_path / "missing"), str(real)])
        monkeypatch.setattr(site, "getsitepackages", lambda: ["", str(packages), str(tmp_path / "missing")])

        binds = _triples(_args(tmp_path), "--ro-bind")

        assert (str(real), str(real)) in binds
        assert (str(packages), str(packages)) in binds
        assert ("", "") not in binds
        assert not any(str(tmp_path / "missing") in pair for pair in binds)

    @pytest.mark.parametrize("covered", [True, False])
    def test_the_resolved_interpreter_is_bound_only_when_no_bound_path_covers_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, covered: bool
    ) -> None:
        resolved = Path(sys.executable).resolve(strict=True)
        bound = {resolved.parent.parent} if covered else {tmp_path}
        monkeypatch.setattr(bwrap_sse_daemon, "follow_links_executable", lambda executable, paths: paths.update(bound))

        binds = _triples(_args(tmp_path), "--ro-bind")

        assert ((str(resolved), str(resolved)) in binds) is (not covered)
        for path in bound:
            assert (str(path), str(path)) in binds

    def test_a_device_is_bound_with_dev_bind_because_a_plain_bind_is_nodev(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(
            file_rules=(FSExposeRule("/dev/null", True, _CONFIG), FSExposeRule("/dev/urandom", False, _CONFIG))
        )

        args = _args(tmp_path, rules)

        assert ("/dev/null", "/dev/null") in _triples(args, "--dev-bind")
        assert ("/dev/urandom", "/dev/urandom") in _triples(args, "--dev-bind")
        assert ("/dev/null", "/dev/null") not in _triples(args, "--bind")
        assert ("/dev/urandom", "/dev/urandom") not in _triples(args, "--ro-bind")

    def test_exposed_paths_are_bound_read_only_or_writable_and_the_temp_dir_is_writable(self, tmp_path: Path) -> None:
        read_only, writable = tmp_path / "ro", tmp_path / "rw"
        rules = EmptyRules._replace(
            file_rules=(FSExposeRule(str(read_only), False, _CONFIG), FSExposeRule(str(writable), True, _CONFIG))
        )

        args = _args(tmp_path, rules)

        assert (str(read_only), str(read_only)) in _triples(args, "--ro-bind")
        assert (str(writable), str(writable)) in _triples(args, "--bind")
        assert (str(tmp_path), str(tmp_path)) in _triples(args, "--bind")
        assert (str(writable), str(writable)) not in _triples(args, "--ro-bind")

    def test_an_ignored_file_is_masked_with_a_placeholder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / ".env").write_text("SECRET=1")
        (project / "data").mkdir()
        temp = tmp_path / "temp"
        temp.mkdir()
        monkeypatch.chdir(project)
        rules = EmptyRules._replace(
            file_rules=(
                FSExposeRule(str(project) + "/", False, _CONFIG),
                IgnoreRule(".env", _CONFIG),
                IgnoreRule("data", _CONFIG),
            )
        )

        with patch.object(bwrap_sse_daemon, "which_command", return_value="/usr/bin/bwrap"):
            args = list(BWrapSSEDaemon("token")._bwrap_args(rules, {}, tmp_path / "pipe", temp))

        masks = {dest: src for src, dest in _triples(args, "--bind")}
        assert (temp / "pysb_ignore_0").is_file() or (temp / "pysb_ignore_1").is_file()
        assert (temp / "pysb_ignore_0").is_dir() or (temp / "pysb_ignore_1").is_dir()
        assert Path(masks[str(project / ".env")]).is_file()
        assert Path(masks[str(project / "data")]).is_dir()


class TestIgnoreMaskHelpers:
    def test_ignore_patterns_are_resolved_below_the_current_directory(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / ".env").write_text("")
        (tmp_path / "sub" / ".env").write_text("")
        (tmp_path / "other").write_text("")

        found = _resolve_ignore_paths(str(tmp_path), [IgnoreRule(".env", _CONFIG)])

        assert sorted(found) == [".env", str(Path("sub") / ".env")]
        assert _resolve_ignore_paths(str(tmp_path), []) == []

    @pytest.mark.parametrize(
        ("path", "inside"),
        [("/a/b/c", True), ("/a", True), ("/a/", True), ("/ab", False), ("/x", False), ("/0", False)],
    )
    def test_a_path_is_inside_an_exposed_directory_or_is_that_directory(self, path: str, inside: bool) -> None:
        assert _is_inside_exposed(path, ["/a/"]) is inside

    def test_a_link_leaving_the_exposed_tree_is_not_reachable(self, tmp_path: Path) -> None:
        exposed = tmp_path / "exposed"
        exposed.mkdir()
        (exposed / "leaves").symlink_to("../outside")
        (exposed / "stays").symlink_to("target")
        (exposed / "target").write_text("")

        assert _is_reachable_in_sandbox(str(exposed / "leaves"), [str(exposed)]) is False
        assert _is_reachable_in_sandbox(str(exposed / "stays"), [str(exposed)]) is True

    def test_a_link_loop_is_not_reachable(self, tmp_path: Path) -> None:
        (tmp_path / "a").symlink_to("b")
        (tmp_path / "b").symlink_to("a")

        assert _is_reachable_in_sandbox(str(tmp_path / "a"), [str(tmp_path)]) is False

    def test_a_missing_or_unreachable_path_does_not_hide_the_following_ones(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret").write_text("")
        exposed = tmp_path / "exposed"
        exposed.mkdir()
        (exposed / "leaves").symlink_to("../outside/secret")
        (exposed / ".env").write_text("")

        targets = _ignore_mask_targets(str(exposed), ["missing", "leaves", ".env"], [str(exposed)])

        assert targets == [str(exposed / ".env")]


class TestNetworkFiltering:
    def test_the_netfilter_rules_allow_the_sse_port_from_the_gateway_before_the_commit(self) -> None:
        socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
        rules = EmptyRules._replace(socket_rules=tuple(socket_rules))

        netfilter = BWrapSSEDaemon._build_netfilter_rules(rules, 8123)

        assert netfilter[-1] == "COMMIT"
        assert (
            f"-A INPUT -p tcp -s {bwrap_sse_daemon.SLIRP_GW}/32 --dport 8123 "
            "-m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
        ) == netfilter[-2]
        assert any(f"-d {bwrap_sse_daemon.SLIRP_DNS}/32 --dport 53" in line for line in netfilter)
        assert any("--dports 443" in line for line in netfilter)

    def _on_launched(self, tmp_path: Path, port: int = 9000) -> tuple[Any, tuple[int, int]]:
        socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
        rules = EmptyRules._replace(socket_rules=tuple(socket_rules))
        daemon = BWrapSSEDaemon("token")
        daemon.port = port
        pipe = os.pipe()
        with (
            patch.object(bwrap_sse_daemon, "which_command", return_value="/usr/bin/tool"),
            patch.object(bwrap_sse_daemon.os, "pipe", return_value=pipe),
        ):
            params = daemon.get_launch_params_for_python_sb(rules, port, "t", "", tmp_path / "pipe", tmp_path)
        return params["on_launched"], pipe

    @staticmethod
    def _is_open(fd: int) -> bool:
        try:
            os.fstat(fd)
        except OSError:
            return False
        return True

    def test_a_failure_before_slirp_started_closes_the_write_end_of_its_pipe(self, tmp_path: Path) -> None:
        on_launched, (_, write_end) = self._on_launched(tmp_path)

        with (
            patch.object(bwrap_sse_daemon, "_sandbox_pid", side_effect=SandBoxError("no pid")),
            patch.object(bwrap_sse_daemon.os, "kill"),
            pytest.raises(SandBoxError, match="no pid"),
        ):
            on_launched(1000)

        assert not self._is_open(write_end)

    def test_a_failure_after_slirp_started_leaves_the_write_end_to_the_watcher(self, tmp_path: Path) -> None:
        on_launched, (_, write_end) = self._on_launched(tmp_path)

        try:
            with (
                patch.object(bwrap_sse_daemon, "_sandbox_pid", return_value=4242),
                patch.object(bwrap_sse_daemon, "_apply_netfilter_from_host"),
                patch.object(bwrap_sse_daemon.threading, "Thread"),
                patch.object(bwrap_sse_daemon, "_slirp_ready", return_value=False),
                patch.object(bwrap_sse_daemon.os, "kill"),
                pytest.raises(SandBoxError, match="slirp4netns"),
            ):
                on_launched(1000)

            assert self._is_open(write_end)
        finally:
            if self._is_open(write_end):
                os.close(write_end)

    def test_a_started_network_forwards_the_incoming_ports_quietly(self, tmp_path: Path) -> None:
        on_launched, (_, write_end) = self._on_launched(tmp_path, port=9100)
        threads: list[dict[str, Any]] = []

        def make_thread(**kw: Any) -> Mock:
            threads.append(kw)
            return Mock()

        extracted: list[dict[str, Any]] = []

        def extract(rules: Any, port: int, **kwargs: Any) -> str:
            extracted.append({"port": port, **kwargs})
            return f"tcp:{port}"

        try:
            with (
                patch.object(bwrap_sse_daemon, "_sandbox_pid", return_value=4242),
                patch.object(bwrap_sse_daemon, "_apply_netfilter_from_host"),
                patch.object(bwrap_sse_daemon.threading, "Thread", side_effect=make_thread),
                patch.object(bwrap_sse_daemon, "_slirp_ready", return_value=True),
                patch.object(bwrap_sse_daemon, "slirp_extract_port_forwards", side_effect=extract),
            ):
                on_launched(1000)
        finally:
            if self._is_open(write_end):
                os.close(write_end)

        assert extracted == [{"port": 9100, "log_wildcard": False}]
        assert [t["target"] for t in threads][-1] is bwrap_sse_daemon.slirp_setup_port_forwarding
        assert threads[-1]["args"][1] == "tcp:9100"
