# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Resolve direct-boot artifacts from the same image as the microvm root disk."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _readable(path: Path) -> None:
    with path.open("rb") as stream:
        if not stream.read(1):
            raise ValueError(f"Empty microvm boot artifact: {path}")


def _identity(image: Path) -> str:
    stat = image.stat()
    return f"{image}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=600).stdout


def _paths(archive: Path) -> list[str]:
    listing = _run("7z", "l", "-slt", "--", str(archive))
    return [line[7:] for line in listing.splitlines() if line.startswith("Path = ") and line[7:] != str(archive)]


def _extract(archive: Path, member: str, target: Path) -> None:
    with target.open("wb") as stream:
        subprocess.run(
            ["7z", "x", "-so", "-spd", "--", str(archive), member],
            stdout=stream,
            stderr=subprocess.PIPE,
            check=True,
            timeout=600,
        )


def ensure_microvm_boot_artifacts(image: Path, params: Mapping[str, Any]) -> tuple[Path, Path]:
    """Return a readable matched kernel/initrd pair or fail before launching QEMU."""
    kernel, initrd = params.get("qemu.microvm_kernel"), params.get("qemu.microvm_initrd")
    if kernel or initrd:
        if not kernel or not initrd:
            raise ValueError("Set both qemu.microvm_kernel and qemu.microvm_initrd")
        pair = Path(kernel).expanduser(), Path(initrd).expanduser()
        for path in pair:
            _readable(path)
        return pair
    image = image.resolve()
    identity = _identity(image)
    cache = image.with_name(image.name + ".microvm-" + hashlib.sha256(identity.encode()).hexdigest())
    pair = cache / "kernel", cache / "initrd"
    try:
        for path in pair:
            _readable(path)
        return pair
    except (OSError, ValueError):
        pass
    if shutil.which("7z") is None:
        raise FileNotFoundError("Install 7zip (7z) or set both qemu.microvm_kernel and qemu.microvm_initrd")
    with tempfile.TemporaryDirectory(prefix=".microvm-", dir=image.parent) as temporary:
        work = Path(temporary)
        raw = work / "disk.raw"
        _run("qemu-img", "convert", "-O", "raw", str(image), str(raw))
        root_paths = _paths(raw)
        for index, member in enumerate([""] + root_paths):
            if member and not member.endswith((".img", ".ext", ".ext4")):
                continue
            partition = work / f"partition-{index}.img" if member else raw
            if member:
                _extract(raw, member, partition)
            try:
                paths = _paths(partition) if member else root_paths
            except subprocess.CalledProcessError:
                if member:
                    partition.unlink()
                continue
            kernels = sorted(path for path in paths if path.startswith("boot/vmlinuz-"))
            for source_kernel in kernels:
                source_initrd = "boot/initrd.img-" + source_kernel.removeprefix("boot/vmlinuz-")
                if source_initrd not in paths:
                    continue
                ready = work / "ready"
                ready.mkdir()
                for source, name in ((source_kernel, "kernel"), (source_initrd, "initrd")):
                    target = ready / name
                    _extract(partition, source, target)
                    _readable(target)
                if _identity(image) != identity:
                    raise ValueError("Root image changed during microvm boot extraction")
                # Publish the pair as one directory; a failed extraction never becomes a cache entry.
                if cache.exists():
                    shutil.rmtree(cache)
                os.rename(ready, cache)
                return pair
            if member:
                partition.unlink()
    raise ValueError(f"No matched vmlinuz/initrd.img pair found in {image}")
