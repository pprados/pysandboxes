# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""QEMU must enforce read-only host shares against native guest code."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parents[2]
_QEMU_REASON = provider_skip_reason("qemu")


@pytest.mark.skipif(bool(_QEMU_REASON), reason=_QEMU_REASON or "")
def test_native_guest_code_cannot_write_an_expose_ro_share(tmp_path: Path) -> None:
    sentinel = tmp_path / "host-sentinel.txt"
    sentinel.write_text("host-before\n")
    profile = tmp_path / "qemu-readonly.profile"
    profile.write_text(
        "\n".join(
            [
                "py-sandbox=false",
                "os-sandbox=qemu",
                "qemu.use_kvm=false",
                f"expose-ro={tmp_path}",
                "",
            ]
        )
    )
    code = f"""
import ctypes
import os

libc = ctypes.CDLL(None, use_errno=True)
fd = libc.open({os.fspath(sentinel)!r}.encode(), os.O_WRONLY | os.O_TRUNC)
if fd < 0:
    print("REFUSED", ctypes.get_errno())
else:
    payload = b"guest-write\\n"
    written = libc.write(fd, payload, len(payload))
    libc.close(fd)
    print("WROTE", written)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            "-c",
            code,
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "REFUSED" in result.stdout
    assert sentinel.read_text() == "host-before\n"
