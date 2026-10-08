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


def test_a_present_image_is_not_downloaded_again(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image.parent.mkdir()
    image.write_bytes(b"qcow")
    calls: list[Path] = []
    monkeypatch.setattr(qemu_fetch_image, "ensure_image", calls.append)

    assert qemu_fetch_image.main() == 0

    assert calls == []
    out = capsys.readouterr().out
    assert f"Default image path:  {image}" in out
    assert "Image already present." in out


def test_a_missing_image_is_downloaded(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(qemu_fetch_image, "ensure_image", calls.append)

    assert qemu_fetch_image.main() == 0

    assert calls == [image]
    assert "Image downloaded successfully." in capsys.readouterr().out


def test_without_a_download_url_the_variables_to_set_are_named(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_url(path: Path) -> None:
        raise FileNotFoundError(f"{path} is missing")

    monkeypatch.setattr(qemu_fetch_image, "ensure_image", no_url)

    assert qemu_fetch_image.main() == 1

    out = capsys.readouterr().out
    assert f"{image} is missing" in out
    assert qemu_fetch_image.ENV_VM_IMAGE_URL in out
    assert qemu_fetch_image.ENV_VM_IMAGE_BASE_URL in out


def test_a_failed_download_is_reported_on_stderr(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(path: Path) -> None:
        raise ConnectionResetError("reset by peer")

    monkeypatch.setattr(qemu_fetch_image, "ensure_image", broken)

    assert qemu_fetch_image.main() == 1

    assert "Download failed: reset by peer" in capsys.readouterr().err
