# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from types import SimpleNamespace

import pytest

from pysandboxes.remote import qemu_sse_daemon as daemon
from pysandboxes.remote.qemu_setup import microvm_mmio_capacity


def test_microvm_command_and_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda _: 4)
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))
    rules = SimpleNamespace(os_sandbox_params={"accel": "tcg"}, file_rules=[])
    assets = daemon._QemuLaunchAssets(Path("root.raw"), Path("seed.iso"), [("share", Path("/tmp"), "/share")])
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    cmd = instance._machine_command(rules, assets, 1234)
    assert "microvm,acpi=off,pcie=off" in cmd
    assert "console=ttyS0 root=/dev/vda1 ro reboot=t" in cmd
    assert "-no-reboot" in cmd
    assert "stdio" in cmd
    assert not any("pci" in arg and "pcie=off" not in arg for arg in cmd)
    assert sum(arg.startswith("virtio-") for arg in cmd) == 4
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda _: 3)
    with pytest.raises(Exception, match="4.*3"):
        instance._machine_command(rules, assets, 1234)


def test_capacity_matches_real_machine() -> None:
    assert microvm_mmio_capacity("qemu-system-x86_64") > 3
