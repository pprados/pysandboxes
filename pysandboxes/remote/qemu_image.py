# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU VM image directory and KVM detection helpers for the qemu provider.

Provides resolution of the standard VM images directory (XDG-compliant),
default image path by Python version and architecture, KVM availability check,
and optional download of the image when missing.
"""

import logging
import os
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

ENV_VM_IMAGES_DIR = "PYSANDBOXES_VM_IMAGES_DIR"
ENV_VM_IMAGE_URL = "PYSANDBOXES_QEMU_IMAGE_URL"
ENV_VM_IMAGE_BASE_URL = "PYSANDBOXES_QEMU_IMAGE_BASE_URL"
XDG_DATA_HOME = "XDG_DATA_HOME"
DEFAULT_VM_IMAGES_SUBDIR = "vm-images"
DEFAULT_IMAGE_PREFIX = "pysandboxes-python"
DEFAULT_IMAGE_SUFFIX = ".qcow2"
# Standard QEMU/VM image repo: Debian Cloud Images (bookworm, generic qcow2)
DEBIAN_CLOUD_BASE = "https://cloud.debian.org/images/cloud/bookworm/latest"
DOWNLOAD_TIMEOUT = 300

# Map platform.machine() to Debian cloud image arch suffix
_ARCH_TO_DEBIAN: dict[str, str] = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "ppc64le": "ppc64el",
}


def get_vm_images_dir() -> Path:
    """Return the directory for VM images (standard, shared-friendly).

    Uses PYSANDBOXES_VM_IMAGES_DIR if set, otherwise $XDG_DATA_HOME/vm-images,
    or ~/.local/share/vm-images when XDG_DATA_HOME is unset.
    """
    env_dir = os.environ.get(ENV_VM_IMAGES_DIR)
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    xdg = os.environ.get(XDG_DATA_HOME)
    if xdg:
        base = Path(xdg).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return (base / DEFAULT_VM_IMAGES_SUBDIR).resolve()


def get_default_image_path(
    python_version: tuple[int, int] | None = None,
    arch: str | None = None,
) -> Path:
    """Return the default image path for the given Python version and architecture.

    Args:
        python_version: (major, minor) e.g. (3, 12). Defaults to sys.version_info[:2].
        arch: Architecture string e.g. x86_64, aarch64. Defaults to platform.machine().

    Returns:
        Path under get_vm_images_dir() with filename like pysandboxes-python-3.12-x86_64.qcow2.
    """
    if python_version is None:
        python_version = sys.version_info[:2]
    if arch is None:
        arch = platform.machine()
    dir_path = get_vm_images_dir()
    name = f"{DEFAULT_IMAGE_PREFIX}-{python_version[0]}.{python_version[1]}-{arch}{DEFAULT_IMAGE_SUFFIX}"
    return dir_path / name


def get_standard_image_url(arch: str | None = None) -> str | None:
    """Return the URL of a standard QEMU-compatible VM image (Debian Cloud Images).

    Uses Debian Bookworm generic qcow2 images from cloud.debian.org.
    Returns None if the current architecture is not supported (amd64, arm64, ppc64el).
    """
    arch = arch or platform.machine()
    debian_arch = _ARCH_TO_DEBIAN.get(arch)
    if not debian_arch:
        return None
    return f"{DEBIAN_CLOUD_BASE}/debian-12-generic-{debian_arch}.qcow2"


def get_download_url(path: Path) -> str | None:
    """Return the URL to use for downloading the image at path, or None if not configured.

    Uses PYSANDBOXES_QEMU_IMAGE_URL (full URL) if set, else PYSANDBOXES_QEMU_IMAGE_BASE_URL
    (base URL + path.name), else the standard Debian Cloud Images URL for the current arch.
    """
    full = os.environ.get(ENV_VM_IMAGE_URL)
    if full and full.strip():
        return full.strip()
    base = os.environ.get(ENV_VM_IMAGE_BASE_URL)
    if base and base.strip():
        return f"{base.rstrip('/')}/{path.name}"
    return get_standard_image_url()


def _default_progress_callback(downloaded: int, total: int | None) -> None:
    """Print download progress to stderr (used when no callback provided)."""
    if total is not None and total > 0:
        pct = min(100, (100 * downloaded) // total)
        mib_d = downloaded / (1024 * 1024)
        mib_t = total / (1024 * 1024)
        msg = f"\r  Downloading VM image: {mib_d:.1f} / {mib_t:.1f} MiB ({pct}%)"
    else:
        msg = f"\r  Downloading VM image: {downloaded / (1024 * 1024):.1f} MiB"
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
    except OSError:
        pass


def download_image(
    path: Path,
    url: str,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> Path:
    """Download the image from url to path. Create parent directory if needed.

    Args:
        path: Destination file path.
        url: URL to download from.
        progress_callback: Optional (downloaded_bytes, total_bytes_or_None) called periodically.

    Returns:
        path on success.

    Raises:
        OSError: On download or write failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    callback = progress_callback or _default_progress_callback
    try:
        logger.info("Downloading QEMU image from %s to %s", url, path)
        req = urllib.request.Request(
            url, headers={"User-Agent": "pysandboxes-qemu-provider/1.0"}
        )
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                raise OSError(f"Download failed: HTTP {resp.status} for {url}")
            total = resp.headers.get("Content-Length")
            total_int: int | None = int(total) if total else None
            size = 0
            with open(partial, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                    callback(size, total_int)
        partial.rename(path)
        callback(size, total_int)
        if total_int is not None:
            try:
                sys.stderr.write("\n")
                sys.stderr.flush()
            except OSError:
                pass
        logger.info("Downloaded %s (%d bytes)", path, size)
        return path
    except Exception as e:
        if partial.exists():
            partial.unlink(missing_ok=True)
        raise OSError(f"Failed to download {url}: {e}") from e


def ensure_image(path: Path) -> Path:
    """Return path if the image file exists; otherwise try to download it.

    If the file is missing, get_download_url(path) is used; when a URL is
    available the image is downloaded to path. Otherwise raises FileNotFoundError.

    Args:
        path: Path to the image file (typically from get_default_image_path()).

    Returns:
        path when the file exists (pre-existing or after download).

    Raises:
        FileNotFoundError: If the image does not exist and no download URL is set.
        OSError: If download fails.
    """
    if path.is_file():
        return path
    url = get_download_url(path)
    if url:
        download_image(path, url)
        return path
    dir_path = path.parent
    msg = (
        f"QEMU image not found: {path}. "
        f"Set {ENV_VM_IMAGE_URL} or {ENV_VM_IMAGE_BASE_URL} to enable auto-download, "
        f"or place the image in {dir_path!s}. "
        "See docs for the guest image contract and standard directory layout."
    )
    raise FileNotFoundError(msg)


def is_kvm_available() -> bool:
    """Return True if /dev/kvm exists and is readable (KVM can be used).

    When False, QEMU should run in TCG mode (no -enable-kvm).
    """
    kvm = Path("/dev/kvm")
    if not kvm.exists():
        return False
    try:
        return os.access(kvm, os.R_OK)
    except OSError:
        return False
