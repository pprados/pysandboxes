# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``python -m pysandboxes.remote.qemu_fetch_image``, as CI and the qemu Dockerfile run it."""

from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_fetch_image


@pytest.fixture
def image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "images" / "default.qcow2"
    monkeypatch.setattr(qemu_fetch_image, "get_vm_images_dir", lambda: path.parent)
    monkeypatch.setattr(qemu_fetch_image, "get_default_image_path", lambda: path)
    return path


def test_a_missing_image_is_downloaded(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(qemu_fetch_image, "ensure_image", calls.append)

    assert qemu_fetch_image.main() == 0

    assert calls == [image]
    assert "Image downloaded successfully." in capsys.readouterr().out


def test_a_failed_download_is_reported_on_stderr(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(path: Path) -> None:
        raise ConnectionResetError("reset by peer")

    monkeypatch.setattr(qemu_fetch_image, "ensure_image", broken)

    assert qemu_fetch_image.main() == 1

    assert "Download failed: reset by peer" in capsys.readouterr().err
