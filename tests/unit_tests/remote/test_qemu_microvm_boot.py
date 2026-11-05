# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Boot extraction tests using small real partitioned cloud-image layouts."""

import multiprocessing
import shutil
import subprocess
from pathlib import Path

import pytest

from pysandboxes.remote import qemu_microvm_boot as boot


@pytest.fixture
def image(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    if any(shutil.which(tool) is None for tool in ("7z", "qemu-img", "mkfs.ext4", "sfdisk")):
        pytest.skip("7z, qemu-img, mkfs.ext4 and sfdisk required")
    tree = tmp_path / "tree" / "boot"
    tree.mkdir(parents=True)
    (tree / "vmlinuz-6.8-test").write_bytes(b"kernel")
    version = "other" if getattr(request, "param", 0) == "mismatch" else "6.8-test"
    (tree / f"initrd.img-{version}").write_bytes(b"initrd")
    fs = tmp_path / "fs.img"
    subprocess.run(["mkfs.ext4", "-q", "-F", "-d", str(tree.parent), str(fs), "16384"], check=True)
    raw = tmp_path / "disk.raw"
    param = getattr(request, "param", 0)
    slot = param if isinstance(param, int) else 0
    with raw.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024)
    subprocess.run(
        ["sfdisk", str(raw)],
        input=f"label: gpt\n{raw}{slot + 1}: start=2048, size=32768, type=L\n",
        text=True,
        capture_output=True,
        check=True,
    )
    with raw.open("r+b") as stream:
        stream.seek(1048576)
        stream.write(fs.read_bytes())
    target = tmp_path / "cloud.qcow2"
    subprocess.run(["qemu-img", "convert", "-f", "raw", "-O", "qcow2", str(raw), str(target)], check=True)
    return target


@pytest.mark.parametrize("image", [0, 2], indirect=True)
def test_discovers_partition_and_reuses_complete_cache(image: Path) -> None:
    kernel, initrd = boot.ensure_microvm_boot_artifacts(image, {})
    assert (kernel.read_bytes(), initrd.read_bytes()) == (b"kernel", b"initrd")
    assert boot.ensure_microvm_boot_artifacts(image, {}) == (kernel, initrd)
    kernel.unlink()
    assert boot.ensure_microvm_boot_artifacts(image, {})[0].read_bytes() == b"kernel"
    image.touch()
    assert boot.ensure_microvm_boot_artifacts(image, {})[0] != kernel


def test_overrides_do_not_require_image_or_extraction(tmp_path: Path) -> None:
    kernel, initrd = tmp_path / "kernel", tmp_path / "initrd"
    kernel.write_bytes(b"kernel")
    initrd.write_bytes(b"initrd")
    params = {"qemu.microvm_kernel": str(kernel), "qemu.microvm_initrd": str(initrd)}
    assert boot.ensure_microvm_boot_artifacts(tmp_path / "absent", params) == (kernel, initrd)
    initrd.unlink()
    with pytest.raises(FileNotFoundError):
        boot.ensure_microvm_boot_artifacts(tmp_path / "absent", params)
    with pytest.raises(ValueError):
        boot.ensure_microvm_boot_artifacts(tmp_path / "absent", {"qemu.microvm_kernel": str(kernel)})


@pytest.mark.parametrize("image", ["mismatch"], indirect=True)
def test_rejects_unmatched_pair_without_publishing_cache(image: Path) -> None:
    with pytest.raises(ValueError, match="matched"):
        boot.ensure_microvm_boot_artifacts(image, {})
    assert not list(image.parent.glob("*.microvm-*"))


def test_malformed_image_leaves_no_published_cache(tmp_path: Path) -> None:
    image = tmp_path / "bad.qcow2"
    image.write_bytes(b"not an image")
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        boot.ensure_microvm_boot_artifacts(image, {})
    assert not list(tmp_path.glob("*.microvm-*"))


def test_interrupted_extraction_does_not_publish_pair(image: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extract = boot._extract

    def interrupt(archive: Path, member: str, target: Path) -> None:
        if member.startswith("boot/initrd.img-"):
            raise InterruptedError("interrupted extraction")
        extract(archive, member, target)

    monkeypatch.setattr(boot, "_extract", interrupt)
    with pytest.raises(InterruptedError):
        boot.ensure_microvm_boot_artifacts(image, {})
    assert not list(image.parent.glob("*.microvm-*"))


def test_concurrent_processes_keep_published_pair(image: Path) -> None:
    context = multiprocessing.get_context("fork")
    first_extracting = context.Event()
    second_extracting = context.Event()
    release_first = context.Event()
    first_returned = context.Event()
    results = context.Queue()

    def resolve(first: bool) -> None:
        extract = boot._extract

        def controlled_extract(archive: Path, member: str, target: Path) -> None:
            if member.startswith("boot/vmlinuz-"):
                if first:
                    first_extracting.set()
                    assert release_first.wait(10)
                else:
                    second_extracting.set()
                    assert first_returned.wait(10)
            extract(archive, member, target)

        boot._extract = controlled_extract
        pair = boot.ensure_microvm_boot_artifacts(image, {})
        results.put(tuple(path.stat().st_ino for path in pair))
        if first:
            first_returned.set()

    processes = [context.Process(target=resolve, args=(first,)) for first in (True, False)]
    try:
        processes[0].start()
        assert first_extracting.wait(10)
        processes[1].start()
        # Without serialization the second extractor reaches the same publication boundary.
        # With serialization it remains blocked until the first publishes its complete pair.
        second_extracting.wait(1)
        release_first.set()
        identities = [results.get(timeout=15), results.get(timeout=15)]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        pair = boot.ensure_microvm_boot_artifacts(image, {})
        assert identities == [tuple(path.stat().st_ino for path in pair)] * 2
        assert tuple(path.read_bytes() for path in pair) == (b"kernel", b"initrd")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(10)
        results.close()
