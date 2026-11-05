# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Strict machine compatibility and real cached guest boot probes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

QEMU = "qemu-system-x86_64"


def _boot_artifacts() -> tuple[Path, Path, Path]:
    from pysandboxes.remote.qemu_image import get_default_image_path
    from pysandboxes.remote.qemu_microvm_boot import ensure_microvm_boot_artifacts

    image = get_default_image_path()
    if not image.is_file():
        pytest.skip("cached Ubuntu image required")
    kernel, initrd = ensure_microvm_boot_artifacts(image, {})
    return image, kernel, initrd


def _accel_args() -> list[str]:
    return ["-enable-kvm"] if os.environ.get("PYSANDBOXES_MICROVM_ACCEL") == "kvm" else []


def _run_stopped_machine(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            QEMU,
            "-machine",
            "microvm,acpi=off,pcie=off",
            "-nodefaults",
            "-no-user-config",
            "-display",
            "none",
            "-serial",
            "none",
            "-monitor",
            "stdio",
            "-S",
            *args,
        ],
        input="quit\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    "device_args",
    [
        ("-netdev", "user,id=net0,restrict=on", "-device", "virtio-net-pci,netdev=net0"),
        ("-device", "virtio-serial-pci"),
        ("-drive", "file=/dev/null,format=raw,if=virtio,readonly=on"),
    ],
)
def test_current_qemu_pci_transports_are_rejected_by_minimal_microvm(device_args: tuple[str, ...]) -> None:
    result = _run_stopped_machine(*device_args)

    assert result.returncode != 0
    assert "No 'PCI' bus found" in result.stderr


def test_current_qemu_virtfs_is_rejected_by_minimal_microvm(tmp_path: Path) -> None:
    result = _run_stopped_machine(
        "-virtfs",
        f"local,path={tmp_path},id=share,security_model=none,mount_tag=share,readonly=on",
    )

    assert result.returncode != 0
    assert "No 'PCI' bus found" in result.stderr


@pytest.mark.parametrize(
    "device_args",
    [
        ("-netdev", "user,id=net0,restrict=on", "-device", "virtio-net-device,netdev=net0"),
        ("-device", "virtio-serial-device"),
        (
            "-blockdev",
            "driver=null-co,node-name=root,size=1048576",
            "-device",
            "virtio-blk-device,drive=root",
        ),
    ],
)
def test_mmio_transports_start_on_minimal_microvm(device_args: tuple[str, ...]) -> None:
    result = _run_stopped_machine(*device_args)

    assert result.returncode == 0, result.stderr


def test_mmio_9p_transport_starts_on_minimal_microvm(tmp_path: Path) -> None:
    result = _run_stopped_machine(
        "-fsdev",
        f"local,id=share,path={tmp_path},security_model=none,readonly=on",
        "-device",
        "virtio-9p-device,fsdev=share,mount_tag=share",
    )

    assert result.returncode == 0, result.stderr


def test_microvm_has_a_finite_mmio_device_budget() -> None:
    devices = tuple(item for _ in range(25) for item in ("-device", "virtio-serial-device"))
    result = _run_stopped_machine(*devices)

    assert result.returncode != 0
    assert "full" in result.stderr


@pytest.mark.slow
def test_direct_kernel_boot_reaches_linux() -> None:
    image, kernel, initrd = _boot_artifacts()
    command = [
        QEMU,
        *_accel_args(),
        "-machine",
        "microvm,acpi=off,pcie=off",
        "-m",
        "768",
        "-nodefaults",
        "-no-user-config",
        "-nographic",
        "-serial",
        "stdio",
        "-kernel",
        str(kernel),
        "-initrd",
        str(initrd),
        "-append",
        "console=ttyS0 root=/dev/vda1 ro reboot=t panic=-1",
        "-snapshot",
        "-drive",
        f"id=root,file={image},format=qcow2,if=none",
        "-device",
        "virtio-blk-device,drive=root",
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=10)

    assert "Linux version" in output
    assert "EXT4-fs (vda1)" in output


@pytest.mark.slow
def test_direct_kernel_boot_operates_mmio_network_and_9p(tmp_path: Path) -> None:
    image, kernel, initrd = _boot_artifacts()
    share = tmp_path / "share"
    share.mkdir()
    (share / "sentinel").write_text("9p-ok\n", encoding="utf-8")
    (tmp_path / "meta-data").write_text(
        "instance-id: pysandboxes-microvm-probe\nlocal-hostname: microvm-probe\n",
        encoding="utf-8",
    )
    (tmp_path / "network-config").write_text(
        "version: 2\nethernets:\n  primary:\n    match:\n      driver: virtio_net\n    dhcp4: true\n",
        encoding="utf-8",
    )
    (tmp_path / "user-data").write_text(
        """#cloud-config
runcmd:
  - |
    set -eu
    mkdir -p /mnt/probe
    mount -t 9p -o trans=virtio,version=9p2000.L probe /mnt/probe
    test "$(cat /mnt/probe/sentinel)" = "9p-ok"
    ip -4 -o address show | tee /dev/ttyS0 | grep -q '10\\.0\\.2\\.'
    echo PYSANDBOXES_MICROVM_MMIO_OK >/dev/ttyS0
    reboot -f
""",
        encoding="utf-8",
    )
    iso = tmp_path / "nocloud.iso"
    subprocess.run(
        [
            "genisoimage",
            "-quiet",
            "-output",
            str(iso),
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            str(tmp_path / "user-data"),
            str(tmp_path / "meta-data"),
            str(tmp_path / "network-config"),
        ],
        check=True,
    )
    command = [
        QEMU,
        *_accel_args(),
        "-machine",
        "microvm,acpi=off,pcie=off",
        "-m",
        "1024",
        "-nodefaults",
        "-no-user-config",
        "-nographic",
        "-serial",
        "stdio",
        "-no-reboot",
        "-kernel",
        str(kernel),
        "-initrd",
        str(initrd),
        "-append",
        "console=ttyS0 root=/dev/vda1 ro reboot=t panic=-1",
        "-snapshot",
        "-drive",
        f"id=root,file={image},format=qcow2,if=none",
        "-device",
        "virtio-blk-device,drive=root",
        "-drive",
        f"id=cidata,file={iso},format=raw,if=none,readonly=on",
        "-device",
        "virtio-blk-device,drive=cidata",
        "-netdev",
        "user,id=net0,restrict=on",
        "-device",
        "virtio-net-device,netdev=net0",
        "-fsdev",
        f"local,id=probe,path={share},security_model=none,readonly=on",
        "-device",
        "virtio-9p-device,fsdev=probe,mount_tag=probe",
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )

    assert "PYSANDBOXES_MICROVM_MMIO_OK" in result.stdout
