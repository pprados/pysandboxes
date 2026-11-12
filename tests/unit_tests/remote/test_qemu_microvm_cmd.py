# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import qemu_setup
from pysandboxes.remote import qemu_sse_daemon as daemon


def test_microvm_command_and_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Mock(return_value=3)
    accel = Mock(return_value=["-enable-kvm"])
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", probe)
    monkeypatch.setattr(daemon, "qemu_accel_args", accel)
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"accel": "tcg"}))
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [("share", Path("/tmp"), "/share")])
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None
    cmd = instance._machine_command(rules, assets, 1234)
    probe.assert_called_once_with(cmd[0], ["-enable-kvm"])
    assert "user,id=net0,hostfwd=tcp:127.0.0.1:1234-:1234" in cmd
    accel.assert_called_once()
    assert "-enable-kvm" in cmd
    assert "microvm,acpi=off,pcie=off,rtc=off" in cmd
    assert cmd[cmd.index("-cpu") + 1] == "max"
    assert "console=ttyS0 root=/dev/sda1 ro reboot=t" in cmd
    assert "virtio-scsi-device,id=scsi0" in cmd
    assert "scsi-hd,drive=root,bus=scsi0.0,channel=0,scsi-id=0,lun=0" in cmd
    assert "scsi-cd,drive=cidata,bus=scsi0.0,channel=0,scsi-id=1,lun=0" in cmd
    assert "-no-reboot" in cmd
    assert "stdio" in cmd
    assert not any("pci" in arg and "pcie=off" not in arg for arg in cmd)
    assert sum(arg.startswith("virtio-") for arg in cmd) == 3
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 2)
    with pytest.raises(Exception, match="3.*2"):
        instance._machine_command(rules, assets, 1234)


def test_microvm_pcie_lifts_the_mmio_limit_on_9p_shares(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Mock(return_value=2)
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", probe)
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda *_: [])
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"microvm_pcie": "true"}))
    shares = [(f"share{i}", Path("/tmp"), f"/share{i}") for i in range(12)]
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), shares)
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None

    cmd = instance._machine_command(rules, assets, 1234)

    probe.assert_not_called()
    assert "microvm,acpi=on,pcie=on,rtc=off" in cmd
    assert sum(arg.startswith("virtio-9p-pci,") for arg in cmd) == 12
    assert not any(arg.startswith("virtio-9p-device") for arg in cmd)


@pytest.mark.parametrize(("write", "security"), [(False, "none"), (True, "mapped-xattr")])
def test_microvm_preserves_interpreter_symlinks_without_changing_writable_shares(
    write: bool, security: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pysandboxes.guard_files import FSExposeRule
    from pysandboxes.sb_types import ConfigLine

    interpreter = tmp_path / "python"
    interpreter.mkdir()
    (interpreter / "python3.11-config").write_text("configuration")
    (interpreter / "python3-config").symlink_to("python3.11-config")
    rule = FSExposeRule(str(interpreter), write, ConfigLine("expose-rw" if write else "expose-ro", Path(), 1))
    rules = EmptyRules._replace(file_rules=(rule,))
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [("pysb_0", interpreter, "/python")])
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 16)
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda *_: [])
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))

    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None
    cmd = instance._machine_command(rules, assets, 1234)

    share = cmd[cmd.index("-fsdev") + 1]
    assert f"security_model={security}" in share
    assert ("readonly=on" in share) is not write


def test_microvm_forwards_the_channel_to_the_unix_socket_the_host_hands_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysandboxes.remote.endpoint import UNIX, Endpoint

    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 16)
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda *_: [])
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [])
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = Endpoint(UNIX, path="/tmp/pysb_x/s")
    instance._resolver_port = None

    cmd = instance._machine_command(EmptyRules, assets, 1234)

    assert "user,id=net0,hostfwd=unix:/tmp/pysb_x/s-:1234" in cmd


def test_microvm_forwards_the_control_port_of_the_guest_with_runtime_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 16)
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda *_: [])
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [])
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = 15353
    instance._control_port = 40000

    cmd = instance._machine_command(EmptyRules, assets, 1234)

    assert "user,id=net0,hostfwd=tcp:127.0.0.1:1234-:1234,hostfwd=tcp:127.0.0.1:40000-:40000" in cmd


def test_capacity_probe_uses_launch_acceleration(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=SimpleNamespace(stdout="type virtio-mmio-bus\ntype virtio-mmio-bus\n"))
    monkeypatch.setattr(qemu_setup.subprocess, "run", run)
    assert qemu_setup.microvm_mmio_capacity("fake-qemu", ["-enable-kvm"]) == 2
    command = run.call_args.args[0]
    assert command[:2] == ["fake-qemu", "-enable-kvm"]
    assert command[command.index("-machine") + 1] == "microvm,acpi=off,pcie=off,rtc=off"
    assert run.call_args.kwargs["input"] == "info qtree\nquit\n"


def test_optional_guest_native_mounts_are_dropped_only_to_fit_capacity() -> None:
    mounts = [
        ("required", Path("/host/project"), "/project"),
        ("ssl", Path("/etc/ssl"), "/etc/ssl"),
        ("pki", Path("/etc/pki"), "/etc/pki"),
    ]

    selected, native_paths = daemon._select_microvm_mounts(mounts, ["/etc/ssl", "/etc/pki"], 4)

    assert selected == [mounts[0], mounts[2]]
    assert native_paths == ["/etc/ssl"]

    selected, native_paths = daemon._select_microvm_mounts(mounts, ["/etc/ssl", "/etc/pki"], 5)
    assert selected == mounts
    assert native_paths == []


def test_optional_guest_native_mounts_do_not_hide_capacity_errors() -> None:
    mounts = [("required", Path("/host/project"), "/project")]

    with pytest.raises(ValueError, match="not mounts"):
        daemon._select_microvm_mounts(mounts, ["/etc/ssl"], 3)

    with pytest.raises(ValueError, match="needs 3 MMIO devices but supports 2"):
        daemon._select_microvm_mounts(mounts, [], 2)

    with pytest.raises(ValueError, match="needs 5 MMIO devices but supports 2"):
        daemon._select_microvm_mounts(
            [
                ("project", Path("/host/project"), "/project"),
                ("ssl", Path("/etc/ssl"), "/etc/ssl"),
                ("pki", Path("/etc/pki"), "/etc/pki"),
            ],
            ["/etc/ssl"],
            2,
        )

    with pytest.raises(ValueError, match="overlaps another mount: /etc/ssl"):
        daemon._select_microvm_mounts(
            [
                ("etc", Path("/host/etc"), "/etc"),
                ("ssl", Path("/etc/ssl"), "/etc/ssl"),
                ("project", Path("/host/project"), "/project"),
            ],
            ["/etc/ssl"],
            4,
        )
