# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`unshare_setup.main`: the commands it issues, what it hides from the sandbox, and what it executes."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import unshare_setup
from pysandboxes.remote.unshare_setup import UnshareSetupConfig


class _Exec(Exception):
    """Raised by the fake `execvp`, which on the real system never returns."""


class _Run:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mounts: list[list[str]] = []
        self.subs: list[list[str]] = []
        self.inputs: dict[str, str] = {}
        self.exec_args: list[str] = []
        self.environ_at_exec: dict[str, str] = {}
        self.chdir: list[str] = []
        self.sleeps: list[float] = []
        self.ip_results: list[tuple[int, str | None]] = []
        self.sub_kwargs: list[dict[str, Any]] = []
        self.show: dict[str, tuple[int, str]] = {}
        self.environ: dict[str, str] = {}


def _config(root: Path, **changes: Any) -> UnshareSetupConfig:
    values: dict[str, Any] = dict(
        dns_servers=[],
        hosts=[],
        mounts_ro=[],
        mounts_rw=[],
        named_pipe="",
        netfilter_rules=[],
        current_dir="",
        ignore_paths=[],
        sandbox_envs={},
        chroot_dir=str(root),
    )
    values.update(changes)
    return UnshareSetupConfig(**values)


def _unlock(path: Path) -> None:
    """Give back the permissions of the masked placeholders, so pytest can remove the tree."""
    if path.is_symlink() or not path.exists():
        return
    path.chmod(0o700)
    if path.is_dir():
        for child in path.iterdir():
            _unlock(child)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    run = _Run(tmp_path / "root")
    ready_read, ready_write = os.pipe()
    os.write(ready_write, b"1")
    os.close(ready_write)
    run.environ = {"PATH": "/usr/bin", "SLIRP_READY_FD": str(ready_read)}
    monkeypatch.setattr(os, "environ", run.environ)

    def fake_run(cmd: list[str], check: bool = True, **kwargs: Any) -> None:
        run.mounts.append(list(cmd))

    def fake_subprocess(cmd: list[str], **kwargs: Any) -> Any:
        run.subs.append(list(cmd))
        run.sub_kwargs.append(dict(kwargs))
        if cmd[0] == "ip" and cmd[2] == "show":
            code, out = run.show.get(cmd[1], (0, ""))
            return SimpleNamespace(returncode=code, stdout=out, stderr="")
        if "input" in kwargs:
            run.inputs[cmd[0]] = kwargs["input"]
        if cmd[0] == "ip" and cmd[1] in ("link", "addr", "route") and cmd[2] in ("set", "add") and run.ip_results:
            code, err = run.ip_results.pop(0)
            return SimpleNamespace(returncode=code, stdout="", stderr=err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_exec(program: str, args: list[str]) -> None:
        run.exec_args = list(args)
        run.environ_at_exec = dict(os.environ)
        raise _Exec

    monkeypatch.setattr(unshare_setup, "_run", fake_run)
    monkeypatch.setattr(unshare_setup.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(unshare_setup.time, "sleep", run.sleeps.append)
    monkeypatch.setattr(unshare_setup.os, "chdir", run.chdir.append)
    monkeypatch.setattr(unshare_setup.os, "execvp", fake_exec)
    monkeypatch.setattr(unshare_setup.shutil, "which", lambda name: f"/opt/{name}")
    yield run
    _unlock(run.root)
    try:
        os.close(ready_read)
    except OSError:
        pass


def _main(
    run: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: UnshareSetupConfig, *command: str
) -> None:
    path = tmp_path / "setup.json"
    path.write_text(config.to_json())
    monkeypatch.setattr(sys, "argv", ["unshare_setup", str(path), "--", *command])
    with pytest.raises(_Exec):
        unshare_setup.main()


def test_without_arguments_it_prints_its_usage_and_stops(
    harness: _Run, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["unshare_setup"])

    with pytest.raises(SystemExit) as stop:
        unshare_setup.main()

    assert stop.value.code == 1
    assert "Usage: unshare_setup <config_path> -- <command>" in capsys.readouterr().err


def test_the_command_follows_the_separator(harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _main(harness, monkeypatch, tmp_path, _config(harness.root), "python", "-c", "pass")

    assert harness.exec_args[-3:] == ["python", "-c", "pass"]
    assert harness.exec_args[harness.exec_args.index("--") + 1 :] == ["python", "-c", "pass"]


def test_without_a_separator_everything_after_the_config_is_the_command(
    harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "setup.json"
    path.write_text(_config(harness.root).to_json())
    monkeypatch.setattr(sys, "argv", ["unshare_setup", str(path), "python", "x.py"])

    with pytest.raises(_Exec):
        unshare_setup.main()

    assert harness.exec_args[-2:] == ["python", "x.py"]


def test_the_sandbox_runs_in_its_own_pid_namespace_with_no_capability(
    harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config(harness.root, current_dir="/work")

    _main(harness, monkeypatch, tmp_path, config, "prog")

    root = str(harness.root)
    assert harness.exec_args == [
        "/usr/bin/unshare",
        "-p",
        "-f",
        f"--mount-proc={root}/proc",
        "/opt/chroot",
        root,
        "/usr/bin/env",
        "--chdir=/work",
        "/opt/setpriv",
        "--inh-caps=-all",
        "--bounding-set=-all",
        "--",
        "prog",
    ]
    assert harness.chdir == [root]


def test_the_sandbox_inherits_only_the_profile_environment_and_pythonpath(
    harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness.environ.update({"API_TOKEN": "secret", "PYTHONPATH": "/project", "PID_FILE": "/run/pid"})
    config = _config(harness.root, sandbox_envs={"LANG": "C", "PATH": "/sandbox/bin"})

    _main(harness, monkeypatch, tmp_path, config, "prog")

    assert harness.environ_at_exec == {"LANG": "C", "PATH": "/sandbox/bin", "PYTHONPATH": "/project"}


def test_without_pythonpath_none_is_invented(harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

    assert harness.environ_at_exec == {}


def test_a_network_that_never_comes_up_stops_the_setup(
    harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(unshare_setup.select, "select", lambda *args: ([], [], []))
    path = tmp_path / "setup.json"
    path.write_text(_config(harness.root).to_json())
    monkeypatch.setattr(sys, "argv", ["unshare_setup", str(path), "--", "prog"])

    with pytest.raises(SystemExit) as stop:
        unshare_setup.main()

    assert stop.value.code == 1
    assert "slirp4netns readiness timeout after 30s" in capsys.readouterr().err
    assert harness.exec_args == []


class TestNetworkConfiguration:
    def test_loopback_is_brought_up_and_tap_gets_its_default_route(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert ["ip", "link", "set", unshare_setup.SLIRP_INTERFACE, "up"] in harness.subs
        assert [
            "ip",
            "route",
            "add",
            "default",
            "via",
            unshare_setup.SLIRP_GATEWAY,
            "dev",
            unshare_setup.SLIRP_INTERFACE,
        ] in harness.subs
        assert ["ip", "link", "set", "lo", "up"] in harness.mounts
        assert harness.sleeps == [1.0]

    def test_a_route_that_already_exists_ends_the_attempts(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        harness.ip_results = [(0, ""), (0, ""), (2, "RTNETLINK answers: File exists")]

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert len([c for c in harness.subs if c[:3] == ["ip", "route", "add"]]) == 1
        assert harness.sleeps == [1.0]

    def test_a_failing_link_is_retried_after_a_pause_then_given_up(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.ip_results = [(1, "no tap")] * 5

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert len([c for c in harness.subs if c[:3] == ["ip", "link", "set"] and c[3] != "lo"]) == 5
        assert harness.sleeps == [0.3, 0.3, 0.3, 0.3, 1.0]
        assert "Could not add default route" in caplog.text

    def test_a_missing_address_is_added_even_when_the_link_is_up(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert [
            "ip",
            "addr",
            "add",
            unshare_setup.SLIRP_TAP_CIDR,
            "dev",
            unshare_setup.SLIRP_INTERFACE,
        ] in harness.subs


class TestFirewall:
    def test_rules_are_loaded_when_there_are_both_resolvers_and_rules(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = _config(harness.root, dns_servers=["192.0.2.53"], netfilter_rules=["*filter", "COMMIT"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        assert harness.inputs["/usr/sbin/iptables-restore"] == "*filter\nCOMMIT"

    @pytest.mark.parametrize(
        ("dns", "rules"), [([], ["*filter"]), (["192.0.2.53"], []), ([], [])], ids=["no-dns", "no-rules", "neither"]
    )
    def test_nothing_is_loaded_otherwise(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dns: list[str], rules: list[str]
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root, dns_servers=dns, netfilter_rules=rules), "prog")

        assert "/usr/sbin/iptables-restore" not in harness.inputs


class TestMounts:

    def test_the_current_directory_is_writable_and_user_mounts_follow_their_mode(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cwd, ro, rw = tmp_path / "cwd", tmp_path / "ro", tmp_path / "rw"
        for path in (cwd, ro, rw):
            path.mkdir()
        config = _config(
            harness.root,
            current_dir=str(cwd),
            mounts_ro=[(str(ro), "/mnt/ro")],
            mounts_rw=[(str(rw), "/mnt/rw")],
        )

        _main(harness, monkeypatch, tmp_path, config, "prog")

        mounted = lambda src, dst: ["mount", "--rbind", str(src), f"{harness.root}{dst}"]  # noqa: E731
        readonly = lambda dst: ["mount", "-o", "remount,ro,bind,nosuid,nodev", f"{harness.root}{dst}"]  # noqa: E731
        assert mounted(cwd, cwd) in harness.mounts
        assert readonly(cwd) not in harness.mounts
        assert mounted(ro, "/mnt/ro") in harness.mounts and readonly("/mnt/ro") in harness.mounts
        assert mounted(rw, "/mnt/rw") in harness.mounts and readonly("/mnt/rw") not in harness.mounts
        assert harness.mounts.index(mounted(ro, "/mnt/ro")) < harness.mounts.index(mounted(rw, "/mnt/rw"))

    def test_no_current_directory_means_no_mount_of_it(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root, current_dir=""), "prog")

        assert not [m for m in harness.mounts if m[:2] == ["mount", "--rbind"] and m[2] == ""]

    def test_the_pseudo_filesystems_are_mounted_with_their_options(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        dev = f"{harness.root}/dev"
        assert ["mount", "-t", "tmpfs", "-o", "mode=755,nosuid", "none", dev] in harness.mounts
        assert ["mount", "-t", "tmpfs", "-o", "mode=1777,nosuid,nodev", "tmpfs", f"{dev}/shm"] in harness.mounts
        assert ["mount", "--bind", "/dev/null", f"{dev}/null"] in harness.mounts

    def test_the_named_pipe_is_exposed_at_the_same_path(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pipe = tmp_path / "pipes" / "config"
        pipe.parent.mkdir()
        pipe.write_text("x")

        _main(harness, monkeypatch, tmp_path, _config(harness.root, named_pipe=str(pipe)), "prog")

        assert ["mount", "--bind", str(pipe), f"{harness.root}{pipe}"] in harness.mounts

    def test_a_named_pipe_that_does_not_exist_is_not_mounted(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root, named_pipe=str(tmp_path / "gone")), "prog")

        assert not [m for m in harness.mounts if str(tmp_path / "gone") in m]


class TestIgnoredPaths:
    def _mounted_cwd(self, harness: _Run, tmp_path: Path) -> Path:
        cwd = tmp_path / "cwd"
        (harness.root / str(cwd).lstrip("/")).mkdir(parents=True)
        return cwd

    def test_a_file_is_masked_by_an_unreadable_placeholder_file(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cwd = self._mounted_cwd(harness, tmp_path)
        (harness.root / str(cwd).lstrip("/") / "secret.txt").write_text("x")
        (harness.root / "tmp").mkdir(parents=True, exist_ok=True)
        config = _config(harness.root, current_dir=str(cwd), ignore_paths=["secret.txt"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        (bind,) = [m for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("secret.txt")]
        placeholder = Path(bind[2])
        assert placeholder.is_file() and placeholder.stat().st_mode & 0o777 == 0
        assert placeholder.parent == harness.root / "tmp"

    def test_a_directory_is_masked_by_an_unreadable_placeholder_directory(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cwd = self._mounted_cwd(harness, tmp_path)
        (harness.root / str(cwd).lstrip("/") / "private").mkdir()
        (harness.root / "tmp").mkdir(parents=True, exist_ok=True)
        config = _config(harness.root, current_dir=str(cwd), ignore_paths=["/private"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        (bind,) = [m for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("private")]
        placeholder = Path(bind[2])
        assert placeholder.is_dir() and placeholder.stat().st_mode & 0o777 == 0

    def test_a_path_that_is_not_in_the_chroot_is_skipped(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cwd = self._mounted_cwd(harness, tmp_path)
        config = _config(harness.root, current_dir=str(cwd), ignore_paths=["absent"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        assert not [m for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("absent")]

    def test_a_failing_overlay_is_reported_and_does_not_stop_the_others(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cwd = self._mounted_cwd(harness, tmp_path)
        base = harness.root / str(cwd).lstrip("/")
        (base / "a").mkdir()
        (base / "b").mkdir()
        (harness.root / "tmp").mkdir(parents=True, exist_ok=True)
        attempts: list[str] = []

        def failing_first(cmd: list[str], check: bool = True, **kwargs: Any) -> None:
            harness.mounts.append(list(cmd))
            if cmd[:2] == ["mount", "--bind"] and cmd[3].endswith(("/a", "/b")):
                attempts.append(cmd[3])
                if len(attempts) == 1:
                    raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(unshare_setup, "_run", failing_first)
        config = _config(harness.root, current_dir=str(cwd), ignore_paths=["a", "b"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        assert len(attempts) == 2
        assert "Could not overlay ignore path" in caplog.text


class TestNameResolution:
    def test_configured_resolvers_are_written_with_the_hosts(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config = _config(harness.root, dns_servers=["192.0.2.53", "192.0.2.54"], hosts=["192.0.2.9 api.test"])

        _main(harness, monkeypatch, tmp_path, config, "prog")

        resolv = next(
            Path(m[2]) for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("etc/resolv.conf")
        )
        hosts = next(Path(m[2]) for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("etc/hosts"))
        assert resolv.read_text() == "nameserver 192.0.2.53\nnameserver 192.0.2.54\n"
        assert hosts.read_text() == "127.0.0.1 localhost\n192.0.2.9 api.test\n"
        assert resolv.parent == harness.root / "tmp"

    def test_without_resolvers_the_host_files_are_used(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        sources = {m[3]: m[2] for m in harness.mounts if m[:2] == ["mount", "--bind"]}
        assert sources[f"{harness.root}/etc/resolv.conf"] == os.path.realpath("/etc/resolv.conf")
        assert sources[f"{harness.root}/etc/hosts"] == os.path.realpath("/etc/hosts")


class TestNetworkProbeDetails:
    def test_a_route_that_fails_for_another_reason_is_retried(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.ip_results = [(0, ""), (0, ""), (2, "Network unreachable")] * 5

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert len([c for c in harness.subs if c[:3] == ["ip", "route", "add"]]) == 5
        assert "Could not add default route" in caplog.text

    @pytest.mark.parametrize("code", [1, -9])
    def test_a_route_command_that_died_is_not_a_success(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
    ) -> None:
        harness.ip_results = [(0, ""), (0, ""), (code, "")] * 5

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert len([c for c in harness.subs if c[:3] == ["ip", "route", "add"]]) == 5

    def test_a_route_failure_without_any_message_is_retried_and_does_not_crash(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        harness.ip_results = [(0, ""), (0, ""), (1, None)] * 5

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert len([c for c in harness.subs if c[:3] == ["ip", "route", "add"]]) == 5

    @pytest.mark.parametrize(
        ("result", "logged"),
        [
            ((1, "Cannot assign"), True),
            ((-9, "killed"), True),
            ((1, "RTNETLINK answers: File exists"), False),
            ((0, ""), False),
        ],
    )
    def test_only_a_real_address_failure_is_logged(
        self,
        harness: _Run,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        result: tuple[int, str | None],
        logged: bool,
    ) -> None:
        harness.ip_results = [(0, ""), result, (0, "")]
        caplog.set_level("DEBUG", logger="pysandboxes.remote.unshare_setup")

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert ("ip addr add tap0" in caplog.text) is logged

    def test_the_state_of_the_interfaces_and_routes_is_logged(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.show = {"addr": (0, "1: lo\n2: tap0\n"), "route": (0, "default via 10.0.2.2\n")}
        caplog.set_level("INFO", logger="pysandboxes.remote.unshare_setup")

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert "  ip addr: 1: lo" in caplog.text and "  ip addr: 2: tap0" in caplog.text
        assert "  ip route: default via 10.0.2.2" in caplog.text
        shows = [i for i, c in enumerate(harness.subs) if c[2:] == ["show"]]
        assert all(harness.sub_kwargs[i] == {"capture_output": True, "text": True} for i in shows)
        assert [harness.subs[i] for i in shows] == [["ip", "addr", "show"], ["ip", "route", "show"]]

    def test_a_failing_state_command_is_not_logged(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.show = {"addr": (1, "garbage\n")}
        caplog.set_level("INFO", logger="pysandboxes.remote.unshare_setup")

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert "garbage" not in caplog.text


class TestMountDetails:
    def test_a_directory_source_gets_a_directory_target(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(unshare_setup, "_run", lambda *a, **k: None)
        src, root = tmp_path / "src", tmp_path / "root"
        src.mkdir()

        unshare_setup._mount_bind(str(src), "/mnt/dir", str(root), readonly=False)

        assert (root / "mnt" / "dir").is_dir()

    def test_a_file_source_gets_a_file_target(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(unshare_setup, "_run", lambda *a, **k: None)
        src, root = tmp_path / "src.txt", tmp_path / "root"
        src.write_text("x")

        unshare_setup._mount_bind(str(src), "/mnt/file.txt", str(root), readonly=False)

        assert (root / "mnt" / "file.txt").is_file()

    def test_the_certificate_stores_are_read_only(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        present = [p for p in ("/etc/ssl", "/etc/pki", "/etc/ca-certificates") if os.path.exists(p)]
        if not present:
            pytest.skip("no certificate store on this host")

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        for path in present:
            assert ["mount", "-o", "remount,ro,bind,nosuid,nodev", f"{harness.root}{path}"] in harness.mounts

    def test_an_existing_shared_memory_directory_is_accepted(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (harness.root / "dev" / "shm").mkdir(parents=True)

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert (harness.root / "dev" / "shm").is_dir()

    def test_a_named_pipe_in_an_existing_directory_is_exposed(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pipe = tmp_path / "pipes" / "config"
        pipe.parent.mkdir()
        pipe.write_text("x")
        (harness.root / str(pipe.parent).lstrip("/")).mkdir(parents=True)

        _main(harness, monkeypatch, tmp_path, _config(harness.root, named_pipe=str(pipe)), "prog")

        assert ["mount", "--bind", str(pipe), f"{harness.root}{pipe}"] in harness.mounts


class TestIgnoredPathDetails:
    def test_without_a_current_directory_a_listed_path_is_still_left_alone(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (harness.root / "tmp").mkdir(parents=True)
        (harness.root / "a").mkdir()

        _main(harness, monkeypatch, tmp_path, _config(harness.root, ignore_paths=["a"]), "prog")

        assert not [m for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3] == f"{harness.root}/a"]

    def test_an_absent_path_does_not_stop_the_ones_after_it(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cwd = tmp_path / "cwd"
        base = harness.root / str(cwd).lstrip("/")
        base.mkdir(parents=True)
        (base / "present").mkdir()
        (harness.root / "tmp").mkdir(exist_ok=True)

        _main(
            harness,
            monkeypatch,
            tmp_path,
            _config(harness.root, current_dir=str(cwd), ignore_paths=["absent", "present"]),
            "prog",
        )

        assert [m for m in harness.mounts if m[:2] == ["mount", "--bind"] and m[3].endswith("/present")]


class TestSignalledCommands:
    def test_two_files_can_be_mounted_into_the_same_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(unshare_setup, "_run", lambda *a, **k: None)
        root = tmp_path / "root"
        for name in ("one", "two"):
            (tmp_path / name).write_text("x")

        unshare_setup._mount_bind(str(tmp_path / "one"), "/mnt/one", str(root), readonly=False)
        unshare_setup._mount_bind(str(tmp_path / "two"), "/mnt/two", str(root), readonly=False)

        assert (root / "mnt" / "one").is_file() and (root / "mnt" / "two").is_file()

    def test_the_output_of_a_state_command_killed_by_a_signal_is_not_logged(
        self, harness: _Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.show = {"addr": (-9, "partial\n")}
        caplog.set_level("INFO", logger="pysandboxes.remote.unshare_setup")

        _main(harness, monkeypatch, tmp_path, _config(harness.root), "prog")

        assert "partial" not in caplog.text
