# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Staging, library closure, and command line of the QEMU provider, without a QEMU binary."""

import logging
import platform
import site
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_socket import parse_rules
from pysandboxes.remote import qemu_sse_daemon as q
from pysandboxes.remote.qemu_sse_daemon import QemuSSEDaemon
from pysandboxes.sb_types import ConfigLine


class TestLdd:
    def _run(self, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> set[Path]:
        monkeypatch.setattr(
            q.subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=""),
        )
        return q._ldd_resolved_paths(Path("/bin/x"))

    def test_the_libraries_named_by_ldd_are_resolved(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        real = tmp_path / "libreal.so.1"
        real.write_text("")
        link = tmp_path / "liblink.so"
        link.symlink_to(real)
        static = Path("/lib64/ld-linux-x86-64.so.2")
        stdout = (
            f"\tlinux-vdso.so.1 (0x00007ffc)\n"
            f"\tliblink.so => {link} (0x0000)\n"
            f"\tgone.so => {tmp_path / 'gone.so'} (0x0000)\n"
            f"\t{static} (0x0000)\n"
        )

        expected = {real.resolve()} | ({static.resolve()} if static.is_file() else set())
        assert self._run(monkeypatch, 0, stdout) == expected

    def test_a_failing_ldd_gives_nothing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        real = tmp_path / "libreal.so.1"
        real.write_text("")

        assert self._run(monkeypatch, 1, f"\tlibreal.so => {real} (0x0)\n") == set()

    def test_a_missing_ldd_gives_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def missing(*args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError("ldd")

        monkeypatch.setattr(q.subprocess, "run", missing)

        assert q._ldd_resolved_paths(Path("/bin/x")) == set()


class TestMultiarchHelpers:
    @pytest.mark.parametrize(
        ("machine", "triplet"),
        [
            ("x86_64", "x86_64-linux-gnu"),
            ("AMD64", "x86_64-linux-gnu"),
            (" arm64 ", "aarch64-linux-gnu"),
            ("armv7l", "arm-linux-gnueabihf"),
            ("riscv64", None),
        ],
    )
    def test_the_machine_maps_to_a_debian_triplet(self, machine: str, triplet: str | None) -> None:
        assert q._debian_multiarch_triplet(machine) == triplet

    def test_the_host_machine_is_used_when_none_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "machine", lambda: "aarch64")

        assert q._debian_multiarch_triplet() == "aarch64-linux-gnu"

    @pytest.mark.parametrize(
        ("raw", "mode"),
        [
            (None, "full"),
            ("sparse", "sparse"),
            ("Minimal", "sparse"),
            ("ldd", "sparse"),
            ("full", "full"),
            ("wide", "full"),
            ("multiarch", "full"),
            ("yes", "full"),
            ("true", "full"),
            ("1", "full"),
        ],
    )
    def test_the_closure_mode_is_sparse_or_full_without_a_warning(
        self, caplog: pytest.LogCaptureFixture, raw: str | None, mode: str
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=q.__name__):
            assert q._normalize_ld_closure_libs_param(raw) == mode

        assert caplog.text == ""

    def test_an_unknown_closure_mode_warns_and_means_full(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=q.__name__):
            assert q._normalize_ld_closure_libs_param("odd") == "full"

        assert "Unknown qemu.ld_closure_libs" in caplog.text


class TestDirectories:
    def test_a_file_adds_its_parent_and_a_directory_itself(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "dir" / "file").write_text("")
        out: set[Path] = set()

        q._add_dir_follow_links(tmp_path / "dir" / "file", out)
        q._add_dir_follow_links(tmp_path / "dir", out)

        assert out == {(tmp_path / "dir").resolve()}

    def test_a_missing_path_and_the_system_libraries_are_left_out(self, tmp_path: Path) -> None:
        out: set[Path] = set()

        q._add_dir_follow_links(tmp_path / "missing", out)
        q._add_dir_follow_links(Path("/usr/lib"), out)

        assert out == set()

    def test_the_peer_lib_directory_holding_libpython_is_added(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        exe = tmp_path / "bin" / "python3.13"
        exe.write_text("")
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "libpython3.13.so.1.0").write_text("")
        other = tmp_path / "other"
        (other / "bin").mkdir(parents=True)
        (other / "bin" / "python").write_text("")
        (other / "lib").mkdir()
        dirs: set[Path] = set()

        q._add_peer_lib_dir_for_executables(dirs, {exe, other / "bin" / "python", tmp_path / "bin" / "absent"})

        assert dirs == {(tmp_path / "lib").resolve()}

    def test_the_directories_holding_libpython_according_to_ldd_are_added(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "python"
        exe.write_text("")
        lib = tmp_path / "libs" / "libpython3.13.so"
        lib.parent.mkdir()
        lib.write_text("")
        libc = tmp_path / "libc" / "libc.so.6"
        libc.parent.mkdir()
        libc.write_text("")
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda elf: {lib, libc})
        dirs: set[Path] = set()

        q._add_libpython_dirs_from_ldd(dirs, {exe, tmp_path / "absent"})

        assert dirs == {lib.parent.resolve()}

    def test_the_execution_mounts_name_each_directory_once_with_the_same_guest_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        interpreter = tmp_path / "interp" / "bin"
        interpreter.mkdir(parents=True)
        exe = interpreter / "python"
        exe.write_text("")
        entry = tmp_path / "entry"
        entry.mkdir()
        packages = tmp_path / "packages"
        packages.mkdir()
        monkeypatch.setattr(q, "follow_links_executable", lambda executable, paths: paths.add(exe))
        monkeypatch.setattr(q, "_bin_paths_include_resolved_interpreter", lambda executable, paths: None)
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda elf: set())
        monkeypatch.setattr(sys, "path", ["", str(tmp_path / "missing"), str(entry), str(entry)])
        monkeypatch.setattr(site, "getsitepackages", lambda: ["", str(packages)])

        specs = q._execution_dirs_mounts()

        hosts = [host for _, host, _ in specs]
        assert hosts == sorted({interpreter.resolve(), entry.resolve(), packages.resolve()}, key=str)
        assert all(guest == str(host) for _, host, guest in specs)
        assert [tag for tag, _, _ in specs] == [f"pysb_exec_{i}" for i in range(3)]

    def test_a_directory_in_the_interpreter_chain_is_mounted_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        prefix = tmp_path / "prefix"
        prefix.mkdir()
        monkeypatch.setattr(q, "follow_links_executable", lambda executable, paths: paths.add(prefix))
        monkeypatch.setattr(q, "_bin_paths_include_resolved_interpreter", lambda executable, paths: None)
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda elf: set())
        monkeypatch.setattr(sys, "path", [])
        monkeypatch.setattr(site, "getsitepackages", lambda: [])

        assert [host for _, host, _ in q._execution_dirs_mounts()] == [prefix.resolve()]

    def test_the_guest_interpreter_is_the_first_resolved_file_of_the_chain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        real = tmp_path / "python3.13"
        real.write_text("")
        monkeypatch.setattr(q, "follow_links_executable", lambda executable, paths: paths.add(real))
        monkeypatch.setattr(q, "_bin_paths_include_resolved_interpreter", lambda executable, paths: None)

        assert q._guest_python_exe_path() == str(real.resolve())


class TestStaging:
    def test_an_exec_tree_is_copied_under_the_stage_and_the_mount_points_at_the_copy(self, tmp_path: Path) -> None:
        host = tmp_path / "host"
        (host / "sub").mkdir(parents=True)
        (host / "sub" / "file").write_text("x")
        single = tmp_path / "single.so"
        single.write_text("y")
        specs: list[tuple[str, Path, str]] = [
            ("pysb_exec_0", host, "/opt/py/lib"),
            ("pysb_exec_1", single, "/opt/py/single.so"),
            ("pysb_1", host, "/data"),
            ("pysb_exec_2", host, "relative/path"),
            ("pysb_exec_3", tmp_path / "missing", "/opt/missing"),
        ]
        temp = tmp_path / "temp"
        temp.mkdir()

        q._stage_exec_virtfs_mounts(temp, specs)

        stage = (temp / "virtfs_stage_exec").resolve()
        assert specs[0] == ("pysb_exec_0", stage / "opt" / "py" / "lib", "/opt/py/lib")
        assert (stage / "opt" / "py" / "lib" / "sub" / "file").read_text() == "x"
        assert specs[1] == ("pysb_exec_1", stage / "opt" / "py" / "single.so", "/opt/py/single.so")
        assert (stage / "opt" / "py" / "single.so").read_text() == "y"
        assert specs[2][1] == host
        assert specs[3][1] == host
        assert specs[4][1] == tmp_path / "missing"

    def test_staging_twice_merges_into_the_same_tree(self, tmp_path: Path) -> None:
        host = tmp_path / "host"
        host.mkdir()
        (host / "file").write_text("x")
        temp = tmp_path / "temp"
        temp.mkdir()
        for _ in range(2):
            q._stage_exec_virtfs_mounts(temp, [("pysb_exec_0", host, "/opt/lib")])

        assert (temp / "virtfs_stage_exec" / "opt" / "lib" / "file").read_text() == "x"

    @pytest.mark.parametrize("any_staged", [True, False])
    def test_the_staging_is_reported_only_when_something_was_staged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, any_staged: bool
    ) -> None:
        host = tmp_path / "host"
        host.mkdir()
        tag = "pysb_exec_0" if any_staged else "pysb_0"
        temp = tmp_path / "temp"
        temp.mkdir()

        with caplog.at_level(logging.DEBUG, logger=q.__name__):
            q._stage_exec_virtfs_mounts(temp, [(tag, host, "/opt/lib")])

        assert ("staged exec mounts" in caplog.text) is any_staged

    def test_the_etc_expose_mount_keeps_its_links_and_a_path_sorting_before_etc_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "hosts").write_text("127.0.0.1 localhost")
        (etc / "alias").symlink_to("hosts")
        before = tmp_path / "before"
        before.mkdir()
        temp = tmp_path / "temp"
        temp.mkdir()
        specs: list[tuple[str, Path, str]] = [("pysb_0", before, "/abc"), ("pysb_1", etc, "/etc")]

        q._stage_overlay_etc_expose_mount(temp, specs)

        staged = (temp / "virtfs_stage_misc").resolve() / "etc"
        assert specs[0][1] == before
        assert (staged / "alias").is_symlink()

    def test_the_etc_expose_mount_is_copied_and_only_the_first_one(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "hosts").write_text("127.0.0.1 localhost")
        other = tmp_path / "other"
        other.mkdir()
        specs: list[tuple[str, Path, str]] = [
            ("pysb_exec_0", etc, "/etc"),
            ("pysb_0", other, "/srv"),
            ("pysb_1", etc, "/etc/"),
            ("pysb_2", etc, "/etc"),
        ]
        temp = tmp_path / "temp"
        temp.mkdir()

        q._stage_overlay_etc_expose_mount(temp, specs)

        staged = (temp / "virtfs_stage_misc").resolve() / "etc"
        assert specs[0][1] == etc
        assert specs[1][1] == other
        assert specs[2] == ("pysb_1", staged, "/etc/")
        assert specs[3][1] == etc
        assert (staged / "hosts").read_text() == "127.0.0.1 localhost"


class TestQemuCommand:
    def _cmd(
        self, tmp_path: Path, image: Path, *, mounts: Any = (), config_dir: Path | None = None
    ) -> tuple[list[str], Any]:
        prepared = MagicMock(return_value=tmp_path / "nocloud.iso")
        with (
            patch.object(q, "get_default_image_path", return_value=image),
            patch.object(q, "ensure_image"),
            patch.object(q, "_file_rules_mounts", return_value=(list(mounts), [])),
            patch.object(q, "prepare_guest_env", prepared),
            patch.object(q, "qemu_accel_args", return_value=[]),
            patch.object(q, "_qemu_binary", return_value="qemu-system-x86_64"),
        ):
            cmd, _ = QemuSSEDaemon("token")._build_qemu_cmd(
                EmptyRules, tmp_path, MagicMock(), 4242, tmp_path / "pipe", config_dir=config_dir
            )
        return list(cmd), prepared

    @pytest.mark.parametrize(
        ("name", "qcow2"),
        [
            ("image.qcow2", True),
            ("jammy-cloudimg.img", True),
            ("plain.img", False),
            ("disk.raw", False),
            ("jammy-cloudimg.raw", False),
            ("jammy-cloudimg.a", False),
        ],
    )
    def test_the_image_format_follows_the_file_name(self, tmp_path: Path, name: str, qcow2: bool) -> None:
        cmd, _ = self._cmd(tmp_path, tmp_path / name)

        drive = cmd[cmd.index("-drive") + 1]
        assert drive == f"file={tmp_path / name},format={'qcow2' if qcow2 else 'raw'},if=virtio"

    def test_each_mount_becomes_a_virtfs_share(self, tmp_path: Path) -> None:
        host = tmp_path / "host"
        host.mkdir()

        cmd, _ = self._cmd(tmp_path, tmp_path / "i.qcow2", mounts=[("pysb_0", host, "/guest")])

        shares = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-virtfs"]
        assert shares == [f"local,path={host},id=pysb_0,security_model=mapped-xattr,mount_tag=pysb_0"]

    @pytest.mark.parametrize("with_dir", [True, False])
    def test_the_config_is_read_from_the_shared_directory_only_when_there_is_one(
        self, tmp_path: Path, with_dir: bool
    ) -> None:
        _, prepared = self._cmd(tmp_path, tmp_path / "i.qcow2", config_dir=tmp_path / "cfg" if with_dir else None)

        expected = f"{q.GUEST_CONFIG_MOUNT}/config.pkl" if with_dir else None
        assert prepared.call_args.kwargs["config_guest_path"] == expected


class TestGuestNetfilter:
    def test_the_filter_allows_the_host_on_the_sse_port_before_the_commit(self) -> None:
        socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
        rules = EmptyRules._replace(socket_rules=tuple(socket_rules))

        netfilter = QemuSSEDaemon("token").guest_netfilter_rules(rules, 8123)

        assert netfilter[-1] == "COMMIT"
        assert netfilter[-2] == (
            "-A INPUT -p tcp -s 10.0.2.2/32 --dport 8123 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
        )
        assert any("-d 10.0.2.3/32 --dport 53" in line for line in netfilter)
