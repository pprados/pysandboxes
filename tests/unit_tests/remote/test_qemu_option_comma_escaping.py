# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A host path or image path containing a comma must not inject extra QEMU sub-options.

QEMU's ``-drive``/``-virtfs``/``-fsdev`` option parser splits each argument on ``,``, so an
un-escaped comma in ``path=``/``file=`` (e.g. from a mount directory legitimately named with
one, or a crafted one) used to be read as the start of another sub-option -- turning a
mount's ``readonly=on`` off, for example.
"""

from pathlib import Path
from unittest.mock import Mock

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import qemu_sse_daemon as daemon


def test_a_comma_in_a_virtfs_host_path_is_escaped_not_split() -> None:
    assets = daemon._QemuLaunchAssets(
        Path("/images/root.img"), Path("/images/seed.iso"), [("pysb_0", Path("/mnt/a,readonly=off"), "/app")]
    )
    instance = object.__new__(daemon.QemuSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None

    cmd = instance._machine_command(EmptyRules, assets, 1234)

    virtfs = cmd[cmd.index("-virtfs") + 1]
    assert "path=/mnt/a,,readonly=off,id=" in virtfs
    assert "path=/mnt/a,readonly=off,id=" not in virtfs


def test_a_comma_in_the_image_path_is_escaped_in_the_drive_argument() -> None:
    assets = daemon._QemuLaunchAssets(Path("/images/root,evil.img"), Path("/images/seed.iso"), [])
    instance = object.__new__(daemon.QemuSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None

    cmd = instance._machine_command(EmptyRules, assets, 1234)

    drives = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-drive"]
    assert any("file=/images/root,,evil.img," in d for d in drives)


def test_a_comma_in_a_microvm_fsdev_host_path_is_escaped(monkeypatch: object) -> None:
    probe = Mock(return_value=3)
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", probe)  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda *_: [])  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon, "ensure_microvm_boot_artifacts", lambda *_: (Path("kernel"), Path("initrd")))  # type: ignore[attr-defined]
    assets = daemon._QemuLaunchAssets(
        Path("/images/root.img"), Path("/images/seed.iso"), [("pysb_0", Path("/mnt/a,security_model=none"), "/app")]
    )
    instance = object.__new__(daemon.QemuMicrovmSSEDaemon)
    instance.endpoint = None
    instance._resolver_port = None

    cmd = instance._machine_command(EmptyRules, assets, 1234)

    fsdev = cmd[cmd.index("-fsdev") + 1]
    assert "path=/mnt/a,,security_model=none," in fsdev
