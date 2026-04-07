"""Unit tests for pysandboxes.remote.qemu_image module."""

import os
import tempfile
from pathlib import Path

import pytest

from pysandboxes.remote.qemu_image import (
    DEBIAN_CLOUD_BASE,
    ENV_VM_IMAGE_BASE_URL,
    ENV_VM_IMAGE_URL,
    ENV_VM_IMAGES_DIR,
    ensure_image,
    get_default_image_path,
    get_download_url,
    get_standard_image_url,
    get_vm_images_dir,
    is_kvm_available,
)


class TestGetVmImagesDir:
    """Tests for get_vm_images_dir."""

    def test_uses_env_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VM_IMAGES_DIR, "/custom/vm-images")
        result = get_vm_images_dir()
        assert result == Path("/custom/vm-images").resolve()

    def test_uses_xdg_data_home_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VM_IMAGES_DIR, raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
        result = get_vm_images_dir()
        assert "vm-images" in str(result)
        assert result == (Path("/xdg/data") / "vm-images").resolve()

    def test_fallback_to_local_share(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VM_IMAGES_DIR, raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        result = get_vm_images_dir()
        assert ".local" in str(result) or "share" in str(result)
        assert result.name == "vm-images"


class TestGetDefaultImagePath:
    """Tests for get_default_image_path."""

    def test_default_filename_format(self) -> None:
        path = get_default_image_path(python_version=(3, 12), arch="x86_64")
        assert path.name == "pysandboxes-python-3.12-x86_64.qcow2"

    def test_uses_sys_version_when_no_args(self) -> None:
        path = get_default_image_path()
        assert "pysandboxes-python" in path.name
        assert path.suffix == ".qcow2"


class TestGetStandardImageUrl:
    """Tests for get_standard_image_url (Debian Cloud Images)."""

    def test_amd64_url(self) -> None:
        url = get_standard_image_url("x86_64")
        assert url == f"{DEBIAN_CLOUD_BASE}/debian-12-generic-amd64.qcow2"

    def test_aarch64_url(self) -> None:
        url = get_standard_image_url("aarch64")
        assert url == f"{DEBIAN_CLOUD_BASE}/debian-12-generic-arm64.qcow2"

    def test_ppc64le_url(self) -> None:
        url = get_standard_image_url("ppc64le")
        assert url == f"{DEBIAN_CLOUD_BASE}/debian-12-generic-ppc64el.qcow2"

    def test_unsupported_arch_returns_none(self) -> None:
        assert get_standard_image_url("mips64") is None


class TestGetDownloadUrl:
    """Tests for get_download_url."""

    def test_full_url_env_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_VM_IMAGE_URL, "https://example.com/image.qcow2")
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        path = get_default_image_path()
        assert get_download_url(path) == "https://example.com/image.qcow2"

    def test_base_url_env_appends_filename(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.setenv(ENV_VM_IMAGE_BASE_URL, "https://example.com/base/")
        path = get_default_image_path(python_version=(3, 12), arch="x86_64")
        assert (
            get_download_url(path)
            == "https://example.com/base/pysandboxes-python-3.12-x86_64.qcow2"
        )

    def test_falls_back_to_debian_when_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        path = get_default_image_path(python_version=(3, 12), arch="x86_64")
        url = get_download_url(path)
        assert url is not None
        assert "cloud.debian.org" in url
        assert "debian-12-generic-amd64.qcow2" in url


class TestEnsureImage:
    """Tests for ensure_image."""

    def test_returns_path_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "existing.qcow2"
            image.write_bytes(b"fake")
            assert ensure_image(image) == image

    def test_raises_when_missing_and_no_download_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        monkeypatch.setattr(
            "pysandboxes.remote.qemu_image.get_standard_image_url",
            lambda arch=None: None,
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "missing.qcow2"
            assert not path.exists()
            with pytest.raises(FileNotFoundError) as exc_info:
                ensure_image(path)
            assert "PYSANDBOXES_QEMU_IMAGE" in str(exc_info.value)


class TestIsKvmAvailable:
    """Tests for is_kvm_available."""

    def test_returns_bool(self) -> None:
        assert isinstance(is_kvm_available(), bool)
