# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The gVisor provider: when it is available, what it launches, and when it refuses to let the guest run."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import gvisor_sse_daemon
from pysandboxes.remote.gvisor_sse_daemon import GVisorSSEDaemon, wait_for_private_netns
from pysandboxes.sb_types import ConfigLine, Envs


def _fake_which(missing: set[str], bin_dir: Path) -> Any:
    return lambda name: None if name in missing else bin_dir / name


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode, b"", stderr)


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A host that has everything: every tool, the sidecar directory, /dev/net/tun, and a guest that starts."""
    bin_dir = tmp_path / "bin"
    (bin_dir / "gvisor-bin").mkdir(parents=True)
    tun = tmp_path / "tun"
    tun.touch()
    monkeypatch.setattr(gvisor_sse_daemon, "which_command", _fake_which(set(), bin_dir))
    monkeypatch.setattr(gvisor_sse_daemon, "_TUN_DEVICE", tun)
    monkeypatch.setattr(gvisor_sse_daemon.subprocess, "run", lambda *a, **k: _completed(0))
    return tmp_path


class TestAvailability:
    @pytest.mark.parametrize("tool", ["runsc", "unshare", "slirp4netns", "iptables-restore", "ip"])
    def test_a_missing_tool_is_named(self, monkeypatch: pytest.MonkeyPatch, host: Path, tool: str) -> None:
        monkeypatch.setattr(gvisor_sse_daemon, "which_command", _fake_which({tool}, host / "bin"))

        assert tool in (GVisorSSEDaemon.unavailable_reason() or "")

    def test_a_host_that_has_everything_makes_the_provider_available(self, host: Path) -> None:
        assert GVisorSSEDaemon.unavailable_reason() is None

    def test_runsc_without_its_sidecar_directory_is_named(self, host: Path) -> None:
        (host / "bin" / "gvisor-bin").rmdir()

        reason = GVisorSSEDaemon.unavailable_reason()

        assert reason is not None and "gvisor-bin" in reason

    def test_the_sidecar_is_looked_for_next_to_the_real_runsc_not_next_to_a_link(
        self, monkeypatch: pytest.MonkeyPatch, host: Path
    ) -> None:
        real = host / "real"
        (real / "gvisor-bin").mkdir(parents=True)
        (real / "runsc").touch()
        (host / "bin" / "gvisor-bin").rmdir()
        (host / "bin" / "runsc").symlink_to(real / "runsc")

        assert GVisorSSEDaemon.unavailable_reason() is None

    def test_a_missing_tun_device_is_named_with_the_container_remedy(
        self, monkeypatch: pytest.MonkeyPatch, host: Path
    ) -> None:
        monkeypatch.setattr(gvisor_sse_daemon, "_TUN_DEVICE", host / "absent")

        reason = GVisorSSEDaemon.unavailable_reason()

        assert reason is not None and "/dev/net/tun" in reason

    def test_a_guest_that_cannot_start_is_reported_with_its_error(
        self, monkeypatch: pytest.MonkeyPatch, host: Path
    ) -> None:
        monkeypatch.setattr(
            gvisor_sse_daemon.subprocess, "run", lambda *a, **k: _completed(1, b"sidecar gvisor_sentry not usable")
        )

        reason = GVisorSSEDaemon.unavailable_reason()

        assert reason is not None and "gvisor_sentry" in reason

    def test_a_filter_that_cannot_load_is_reported_before_any_guest_runs(
        self, monkeypatch: pytest.MonkeyPatch, host: Path
    ) -> None:
        def run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            if "iptables-restore" in cmd[-2]:
                return _completed(1, b"iptables-restore: line 1 failed")
            return _completed(0)

        monkeypatch.setattr(gvisor_sse_daemon.subprocess, "run", run)

        reason = GVisorSSEDaemon.unavailable_reason()

        assert reason is not None and "iptables-restore" in reason

    def test_a_smoke_that_hangs_makes_it_unavailable(self, monkeypatch: pytest.MonkeyPatch, host: Path) -> None:
        def hang(*args: Any, **kwargs: Any) -> None:
            raise subprocess.TimeoutExpired("runsc", 1)

        monkeypatch.setattr(gvisor_sse_daemon.subprocess, "run", hang)

        assert GVisorSSEDaemon.unavailable_reason() is not None


class TestPlatform:
    def test_a_known_platform_is_accepted(self) -> None:
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"platform": "ptrace"}))

        assert GVisorSSEDaemon._platform(rules) == "ptrace"

    def test_kvm_without_a_usable_kvm_device_is_refused_with_its_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(gvisor_sse_daemon, "_KVM_DEVICE", tmp_path / "absent")
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"platform": "kvm"}))

        with pytest.raises(SandBoxError, match="/dev/kvm|kvm"):
            GVisorSSEDaemon._platform(rules)

    def test_kvm_with_a_usable_kvm_device_is_accepted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        device = tmp_path / "kvm"
        device.touch()
        monkeypatch.setattr(gvisor_sse_daemon, "_KVM_DEVICE", device)
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"platform": "kvm"}))

        assert GVisorSSEDaemon._platform(rules) == "kvm"

    def test_the_default_platform_needs_no_device(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(gvisor_sse_daemon, "_KVM_DEVICE", tmp_path / "absent")

        assert GVisorSSEDaemon._platform(EmptyRules) == "systrap"


class TestRules:
    def test_the_profile_keys_of_the_provider_are_parsed_and_the_others_passed_through(self) -> None:
        daemon = GVisorSSEDaemon("token")
        lines = [ConfigLine("gvisor.platform=kvm", Path("p"), 1), ConfigLine("expose-ro=/data", Path("p"), 2)]

        params, other = daemon.parse_rules(lines, [])

        assert dict(params) == {"platform": "kvm"}
        assert [r.rule for r in other] == ["expose-ro=/data"]


class TestLaunchCommand:
    def _launch(
        self, tmp_path: Path, envs: dict[str, str] | None = None, **rule_overrides: Any
    ) -> tuple[list[str], dict[str, str], dict[str, Any]]:
        (tmp_path / "run").mkdir()
        data = tmp_path / "data"
        data.mkdir()
        rules = EmptyRules._replace(
            envs=Envs(envs if envs is not None else {"ALLOWED": "yes"}),
            file_rules=(FSExposeRule(str(data), False, ConfigLine("e", Path("p"), 1)),),
            **rule_overrides,
        )
        daemon = GVisorSSEDaemon("token")
        daemon.port = 4242
        args, env = daemon.subprocess_cmd(rules, {}, tmp_path / "run" / "pipe", tmp_path / "run")
        spec = json.loads((tmp_path / "run" / "gvisor" / "config.json").read_text())
        return args, dict(env), spec

    def test_the_launcher_creates_a_private_user_and_network_namespace_first(self, tmp_path: Path) -> None:
        args, _, _ = self._launch(tmp_path)

        assert args[:4] == ["unshare", "--user", "--map-root-user", "--net"]
        assert args[4:6] == ["--", "sh"]

    def test_the_guest_runs_the_sandbox_daemon_with_the_environment_of_the_rules_only(self, tmp_path: Path) -> None:
        _, _, spec = self._launch(tmp_path)

        assert spec["process"]["args"][-2:] == ["-m", "pysandboxes.remote.main_sandbox"]
        env = dict(item.split("=", 1) for item in spec["process"]["env"])
        assert env["ALLOWED"] == "yes"
        assert "HOME" not in env and "USER" not in env, "the host environment does not leak into the guest"

    def test_runsc_is_stopped_from_inventing_a_home_for_the_guest(self, tmp_path: Path) -> None:
        _, _, spec = self._launch(tmp_path)

        assert spec["process"]["args"][:3] == ["/usr/bin/env", "-u", "HOME"], "runsc adds HOME=/ when none is set"
        assert spec["process"]["args"][-2:] == ["-m", "pysandboxes.remote.main_sandbox"]

    def test_a_home_the_rules_allow_is_kept(self, tmp_path: Path) -> None:
        _, _, spec = self._launch(tmp_path, envs={"HOME": "/home/me"})

        assert "/usr/bin/env" not in spec["process"]["args"]
        assert "HOME=/home/me" in spec["process"]["env"]

    def test_the_guest_finds_its_python_without_the_host_environment(self, tmp_path: Path) -> None:
        _, _, spec = self._launch(tmp_path)
        env = dict(item.split("=", 1) for item in spec["process"]["env"])

        assert env["PYTHONHOME"] == sys.base_prefix
        assert env["PYTHONPATH"]

    def test_the_guest_sees_the_rules_exposures_and_its_config_but_not_the_run_directory(self, tmp_path: Path) -> None:
        _, _, spec = self._launch(tmp_path)
        mounts = {m["destination"]: m["options"] for m in spec["mounts"] if m["type"] == "bind"}

        assert "ro" in mounts[str(tmp_path / "data")]
        assert "ro" in mounts[str(tmp_path / "run" / "gvisor" / "guest")]
        assert str(tmp_path / "run") not in mounts, "it holds the spec, the filter and the config pipe"
        assert str(tmp_path / "run" / "gvisor") not in mounts

    def test_the_guest_reads_its_config_from_the_directory_it_can_see(self, tmp_path: Path) -> None:
        args, _, _ = self._launch(tmp_path)

        assert str(tmp_path / "run" / "gvisor" / "guest" / "config") in args[args.index("-c") + 1]

    def test_an_unknown_platform_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SandBoxError, match="platform"):
            self._launch(tmp_path, os_sandbox_params=ImmutableDict({"platform": "rm -rf"}))

    def test_a_known_platform_is_passed_to_runsc(self, tmp_path: Path) -> None:
        args, _, _ = self._launch(tmp_path, os_sandbox_params=ImmutableDict({"platform": "ptrace"}))

        assert "--platform=ptrace" in args[args.index("-c") + 1]

    def test_runsc_runs_the_bundle_without_the_network_of_its_own_and_without_host_sockets(
        self, tmp_path: Path
    ) -> None:
        args, _, _ = self._launch(tmp_path)
        script = args[args.index("-c") + 1]

        assert "--network=host" in script, "the netns is the private one the launcher created and filtered"
        assert "--host-uds=none" in script

    def test_the_host_side_launcher_has_a_path_of_its_own(self, tmp_path: Path) -> None:
        _, env, _ = self._launch(tmp_path)

        assert "/usr/bin" in env["PATH"]

    def test_the_filter_it_loads_denies_by_default_and_opens_the_daemon_port(self, tmp_path: Path) -> None:
        self._launch(tmp_path)

        rules = (tmp_path / "run" / "gvisor" / "rules").read_text()

        assert ":OUTPUT DROP" in rules and "--dport 4242" in rules and rules.rstrip().endswith("COMMIT")

    def test_the_network_is_not_ready_until_the_host_says_so(self, tmp_path: Path) -> None:
        args, _, _ = self._launch(tmp_path)

        assert not (tmp_path / "run" / "gvisor" / "ready").exists()
        assert str(tmp_path / "run" / "gvisor" / "ready") in args[args.index("-c") + 1]

    def test_the_daemon_listens_on_every_interface_of_the_private_network(self) -> None:
        assert GVisorSSEDaemon("token")._sse_bind_host([]) == "0.0.0.0"

    def test_the_daemon_is_reached_through_the_loopback_forwarded_by_slirp(self) -> None:
        assert GVisorSSEDaemon("token").base_url == "http://127.0.0.1:{PORT}"


class TestPrivateNetns:
    """A namespace is identified by the inode of its file under ``/proc/<pid>/ns``, as ``ip netns identify`` does.

    The files below stand for those: a hard link is the same namespace, a file of its own is another one.
    """

    def _host(self, tmp_path: Path) -> Path:
        ns = tmp_path / "self" / "ns"
        ns.mkdir(parents=True)
        (ns / "net").write_text("host")
        return ns / "net"

    def _proc(self, tmp_path: Path, pid: int, *, same_netns_as: Path | None, uid_map: str) -> None:
        ns = tmp_path / str(pid) / "ns"
        ns.mkdir(parents=True)
        if same_netns_as is None:
            (ns / "net").write_text("own")
        else:
            os.link(same_netns_as, ns / "net")
        (tmp_path / str(pid) / "uid_map").write_text(uid_map)

    def test_it_returns_once_the_process_has_left_the_host_network_namespace(self, tmp_path: Path) -> None:
        self._host(tmp_path)
        self._proc(tmp_path, 77, same_netns_as=None, uid_map="0 1000 1\n")

        wait_for_private_netns(77, timeout=1, proc=tmp_path)

    def test_a_process_still_in_the_host_network_namespace_is_never_attached(self, tmp_path: Path) -> None:
        host = self._host(tmp_path)
        self._proc(tmp_path, 77, same_netns_as=host, uid_map="0 1000 1\n")

        with pytest.raises(SandBoxError, match="network namespace"):
            wait_for_private_netns(77, timeout=0.3, proc=tmp_path)

    def test_a_process_whose_uid_map_is_not_written_yet_is_not_ready(self, tmp_path: Path) -> None:
        self._host(tmp_path)
        self._proc(tmp_path, 77, same_netns_as=None, uid_map="")

        with pytest.raises(SandBoxError):
            wait_for_private_netns(77, timeout=0.3, proc=tmp_path)

    def test_a_process_that_is_gone_is_reported_not_attached(self, tmp_path: Path) -> None:
        self._host(tmp_path)

        with pytest.raises(SandBoxError, match="network namespace"):
            wait_for_private_netns(77, timeout=0.3, proc=tmp_path)


class TestStartingTheNetwork:
    def _daemon(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, slirp_ready: bool) -> GVisorSSEDaemon:
        daemon = GVisorSSEDaemon("token")
        daemon.port = 4242
        daemon._ready_file = tmp_path / "ready"
        daemon._api_socket = str(tmp_path / "api.sock")
        daemon._ports_spec = ""
        monkeypatch.setattr(gvisor_sse_daemon, "wait_for_private_netns", lambda pid, **k: None)

        def fake_watcher(event: Any, pipe_w: int, api_socket: str, **kwargs: Any) -> None:
            if slirp_ready:
                os.write(pipe_w, b"1")
            os.close(pipe_w)

        monkeypatch.setattr(gvisor_sse_daemon, "slirp_run_watcher", fake_watcher)
        return daemon

    def test_the_guest_is_released_once_slirp_is_up(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        daemon = self._daemon(tmp_path, monkeypatch, slirp_ready=True)

        daemon._on_process_launched(os.getpid())

        assert (tmp_path / "ready").exists()

    def test_the_guest_is_killed_and_never_released_when_slirp_does_not_come_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        daemon = self._daemon(tmp_path, monkeypatch, slirp_ready=False)
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(gvisor_sse_daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))

        with pytest.raises(SandBoxError, match="slirp4netns"):
            daemon._on_process_launched(4321)

        assert not (tmp_path / "ready").exists()
        assert (4321, signal.SIGKILL) in killed
