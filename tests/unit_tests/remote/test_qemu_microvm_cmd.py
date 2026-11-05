# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pysandboxes.remote import qemu_sse_daemon as daemon
from pysandboxes.remote import qemu_setup


def test_microvm_command_and_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Mock(return_value=4)
    accel = Mock(return_value=["-enable-kvm"])
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", probe)
    monkeypatch.setattr(daemon, "qemu_accel_args", accel)
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    rules = SimpleNamespace(os_sandbox_params={"accel": "tcg"}, file_rules=[])
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [("share", Path("/tmp"), "/share")])
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    cmd = instance._machine_command(rules, assets, 1234)
    probe.assert_called_once_with(cmd[0], ["-enable-kvm"])
    accel.assert_called_once()
    assert "-enable-kvm" in cmd
    assert "microvm,acpi=off,pcie=off" in cmd
    assert "console=ttyS0 root=/dev/vda1 ro reboot=t" in cmd
    assert "-no-reboot" in cmd
    assert "stdio" in cmd
    assert not any("pci" in arg and "pcie=off" not in arg for arg in cmd)
    assert sum(arg.startswith("virtio-") for arg in cmd) == 4
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 3)
    with pytest.raises(Exception, match="4.*3"):
        instance._machine_command(rules, assets, 1234)


def test_capacity_probe_uses_launch_acceleration(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=SimpleNamespace(stdout="type virtio-mmio-bus\ntype virtio-mmio-bus\n"))
    monkeypatch.setattr(qemu_setup.subprocess, "run", run)
    assert qemu_setup.microvm_mmio_capacity("fake-qemu", ["-enable-kvm"]) == 2
    command = run.call_args.args[0]
    assert command[:2] == ["fake-qemu", "-enable-kvm"]
    assert command[command.index("-machine") + 1] == "microvm,acpi=off,pcie=off"
    assert run.call_args.kwargs["input"] == "info qtree\nquit\n"
