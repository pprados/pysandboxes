"""Unit tests for pysandboxes.remote.qemu_image module."""

import tempfile
from pathlib import Path

import pytest

from pysandboxes.remote.qemu_image import (
    DEBIAN_CLOUD_BASE,
    ENV_VM_IMAGE_BASE_URL,
    ENV_VM_IMAGE_URL,
    ENV_VM_IMAGES_DIR,
    PYTHON_VERSION_TO_UBUNTU_IMAGE,
    UBUNTU_CLOUD_IMAGES_ROOT,
    UBUNTU_CLOUD_RELEASES_BASE,
    ensure_image,
    get_default_image_filename,
    get_default_image_path,
    get_download_url,
    get_standard_download_url,
    get_standard_image_url,
    get_ubuntu_image_url_for_python_version,
    get_vm_images_dir,
    is_kvm_available,
    normalize_qemu_m_memory_arg,
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

    def test_filename_matches_download_url_for_ubuntu_versions(self) -> None:
        """Default filename is the same as the remote (URL last segment) for reuse."""
        path = get_default_image_path(python_version=(3, 12), arch="x86_64")
        assert path.name == "ubuntu-24.04-server-cloudimg-amd64.img"
        url = get_standard_download_url(python_version=(3, 12), arch="x86_64")
        assert url is not None
        assert path.name == url.rstrip("/").split("/")[-1]

    def test_filename_matches_download_url_for_python_3_14(self) -> None:
        path = get_default_image_path(python_version=(3, 14), arch="x86_64")
        assert path.name == "ubuntu-25.04-server-cloudimg-amd64.img"
        url = get_standard_download_url(python_version=(3, 14), arch="x86_64")
        assert url is not None
        assert path.name == url.rstrip("/").split("/")[-1]

    def test_uses_sys_version_when_no_args(self) -> None:
        path = get_default_image_path()
        assert path.name == get_default_image_filename()
        # Filename is the standard image's URL segment, or python-3.x-arch.qcow2 when
        # the running version has no mapped image. The segment does not always carry
        # "ubuntu": a release named by its codename gives <codename>-server-cloudimg-*.
        url = get_standard_download_url()
        if url:
            assert path.name == url.rstrip("/").split("/")[-1]
        else:
            assert path.suffix == ".qcow2" and "python" in path.name


class TestGetStandardDownloadUrl:
    """Tests for get_standard_download_url."""

    def test_returns_ubuntu_url_for_mapped_version(self) -> None:
        url = get_standard_download_url(python_version=(3, 12), arch="x86_64")
        assert url is not None
        assert "ubuntu" in url
        assert "24.04" in url
        assert url.endswith("ubuntu-24.04-server-cloudimg-amd64.img")

    def test_returns_debian_url_for_unmapped_version(self) -> None:
        url = get_standard_download_url(python_version=(3, 9), arch="x86_64")
        assert url is not None
        assert "debian" in url
        assert "debian-12-generic-amd64.qcow2" in url


class TestGetDefaultImageFilename:
    """Tests for get_default_image_filename."""

    def test_matches_url_filename_for_ubuntu(self) -> None:
        name = get_default_image_filename(python_version=(3, 12), arch="x86_64")
        assert name == "ubuntu-24.04-server-cloudimg-amd64.img"

    def test_fallback_for_unsupported_arch(self) -> None:
        name = get_default_image_filename(python_version=(3, 12), arch="mips64")
        assert name == "python-3.12-mips64.qcow2"


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


class TestGetUbuntuImageUrlForPythonVersion:
    """Tests for get_ubuntu_image_url_for_python_version (mapping 3.10–3.14)."""

    def test_mapping_3_10_amd64(self) -> None:
        url = get_ubuntu_image_url_for_python_version(3, 10, "x86_64")
        assert url is not None
        assert UBUNTU_CLOUD_RELEASES_BASE in url
        assert "22.04" in url
        assert "ubuntu-22.04-server-cloudimg-amd64.img" in url

    def test_mapping_3_13_amd64(self) -> None:
        url = get_ubuntu_image_url_for_python_version(3, 13, "x86_64")
        assert url is not None
        assert "25.04" in url
        assert "ubuntu-25.04-server-cloudimg-amd64.img" in url

    def test_mapping_3_14_amd64(self) -> None:
        url = get_ubuntu_image_url_for_python_version(3, 14, "x86_64")
        assert url is not None
        assert "25.04" in url
        assert "ubuntu-25.04-server-cloudimg-amd64.img" in url

    def test_codename_release_uses_current_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A codename entry still resolves under {codename}/current/.

        No supported version maps to a codename any more (they track the devel series,
        whose glibc outruns the host's), but the branch stays reachable by config.
        """
        monkeypatch.setitem(
            PYTHON_VERSION_TO_UBUNTU_IMAGE,
            (3, 14),
            ("resolute", "resolute-server-cloudimg-{arch}.img"),
        )
        url = get_ubuntu_image_url_for_python_version(3, 14, "x86_64")
        assert url is not None
        assert UBUNTU_CLOUD_IMAGES_ROOT in url
        assert "/resolute/current/" in url
        assert url.endswith("resolute-server-cloudimg-amd64.img")

    def test_unsupported_version_returns_none(self) -> None:
        assert get_ubuntu_image_url_for_python_version(3, 9, "x86_64") is None

    def test_unsupported_arch_returns_none(self) -> None:
        assert get_ubuntu_image_url_for_python_version(3, 12, "mips64") is None

    def test_dict_has_five_entries(self) -> None:
        assert len(PYTHON_VERSION_TO_UBUNTU_IMAGE) == 5
        assert (3, 10) in PYTHON_VERSION_TO_UBUNTU_IMAGE
        assert (3, 11) in PYTHON_VERSION_TO_UBUNTU_IMAGE
        assert (3, 12) in PYTHON_VERSION_TO_UBUNTU_IMAGE
        assert (3, 13) in PYTHON_VERSION_TO_UBUNTU_IMAGE
        assert (3, 14) in PYTHON_VERSION_TO_UBUNTU_IMAGE


class TestGetDownloadUrl:
    """Tests for get_download_url."""

    def test_full_url_env_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VM_IMAGE_URL, "https://example.com/image.qcow2")
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        path = get_default_image_path()
        assert get_download_url(path) == "https://example.com/image.qcow2"

    def test_base_url_env_appends_path_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.setenv(ENV_VM_IMAGE_BASE_URL, "https://example.com/base/")
        path = get_default_image_path(python_version=(3, 12), arch="x86_64")
        assert get_download_url(path) == f"https://example.com/base/{path.name}"

    def test_falls_back_to_standard_url_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        path = get_default_image_path()
        url = get_download_url(path)
        assert url is not None
        # Filename in path must match URL so download and use share the same file
        assert path.name == url.rstrip("/").split("/")[-1]


class TestEnsureImage:
    """Tests for ensure_image."""

    def test_returns_path_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "existing.qcow2"
            image.write_bytes(b"fake")
            assert ensure_image(image) == image

    def test_raises_when_missing_and_no_download_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(ENV_VM_IMAGE_BASE_URL, raising=False)
        monkeypatch.setattr(
            "pysandboxes.remote.qemu_image.get_standard_download_url",
            lambda python_version=None, arch=None: None,
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


class TestNormalizeQemuMMemoryArg:
    """Tests for normalize_qemu_m_memory_arg (``qemu -m`` size strings)."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2048", "2048"),
            ("  512M ", "512M"),
            ("2G", "2G"),
            ("2g", "2g"),
            ("10G", "10G"),
            ("512K", "512K"),
            ("1T", "1T"),
        ],
    )
    def test_accepts_qemu_style_sizes(self, raw: str, expected: str) -> None:
        assert normalize_qemu_m_memory_arg(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["", "2GB", "2GiB", "foo", "2 G", "-1", "1.5G"],
    )
    def test_invalid_falls_back_to_default(self, raw: str) -> None:
        assert normalize_qemu_m_memory_arg(raw, default="2048") == "2048"

    def test_custom_default(self) -> None:
        assert normalize_qemu_m_memory_arg("nope", default="1024") == "1024"
