# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Kernel providers must enforce read-only host shares against native code."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parents[2]
_PROVIDERS = ("qemu", "unshare", "firejail", "landlock", "bwrap")


@pytest.fixture
def exposed_dir(provider: str, tmp_path: Path) -> Iterator[Path]:
    if provider == "qemu":
        yield tmp_path
        return
    with tempfile.TemporaryDirectory(prefix=".native-readonly-", dir=ROOT_DIR) as directory:
        yield Path(directory)


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_native_code_cannot_write_a_read_only_share(provider: str, tmp_path: Path, exposed_dir: Path) -> None:
    if reason := provider_skip_reason(provider):
        pytest.skip(reason)

    sentinel = exposed_dir / "host-sentinel.txt"
    sentinel.write_text("host-before\n")
    profile = tmp_path / f"{provider}-readonly.profile"
    profile.write_text(
        "\n".join(
            [
                "py-sandbox=false",
                f"os-sandbox={provider}",
                *(["qemu.use_kvm=false"] if provider == "qemu" else []),
                f"expose-ro={exposed_dir}",
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
        cwd=ROOT_DIR if provider == "qemu" else tmp_path,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert sentinel.read_text() == "host-before\n"
