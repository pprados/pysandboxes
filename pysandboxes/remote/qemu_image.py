# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU VM image directory and KVM detection helpers for the qemu provider.

Provides resolution of the standard VM images directory (XDG-compliant),
default image path by Python version and architecture, KVM availability check,
and optional download of the image when missing.
"""

import hashlib
import logging
import os
import platform
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ``qemu -m``: non-negative integer, optional single suffix k/M/G/T/P/E (see ``qemu-system -help``).
_QEMU_M_MEMORY_ARG = re.compile(r"^\d+([kKmMgGtTpPeE])?$")


def normalize_qemu_m_memory_arg(raw: str, default: str = "2048") -> str:
    """Return a value safe to pass to ``qemu-system-* -m`` (RAM size).

    QEMU accepts a non-negative integer, optionally with a single suffix letter
    ``k``, ``M``, ``G``, ``T``, ``P``, or ``E`` (e.g. ``512M``, ``2G``, ``512K``).
    Forms like ``2GB`` or ``2GiB`` are not valid for QEMU's ``-m`` parser and are
    rejected; the default (MiB) is used instead.
    """
    s = raw.strip()
    if not s:
        return default
    if _QEMU_M_MEMORY_ARG.fullmatch(s):
        return s
    logger.warning("Invalid qemu.memory %r; using default %r", raw, default)
    return default


ENV_VM_IMAGES_DIR = "PYSANDBOXES_VM_IMAGES_DIR"
ENV_VM_IMAGE_URL = "PYSANDBOXES_QEMU_IMAGE_URL"
ENV_VM_IMAGE_BASE_URL = "PYSANDBOXES_QEMU_IMAGE_BASE_URL"
XDG_DATA_HOME = "XDG_DATA_HOME"
DEFAULT_VM_IMAGES_SUBDIR = "vm-images"
DEFAULT_IMAGE_PREFIX = "python"
DEFAULT_IMAGE_SUFFIX = ".qcow2"
# Standard QEMU/VM image repo: Debian Cloud Images (bookworm, generic qcow2)
DEBIAN_CLOUD_BASE = "https://cloud.debian.org/images/cloud/bookworm/latest"
# Debian Trixie (13) provides Python 3.13; use PYSANDBOXES_QEMU_IMAGE_URL with e.g.:
# https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2
DEBIAN_TRIXIE_CLOUD_BASE = "https://cloud.debian.org/images/cloud/trixie/latest"
DOWNLOAD_TIMEOUT = 300
# Pins the digest of a custom download URL (PYSANDBOXES_QEMU_IMAGE_URL/_BASE_URL) without
# relying on a neighbor checksums file.
ENV_VM_IMAGE_SHA256 = "PYSANDBOXES_QEMU_IMAGE_SHA256"
CHECKSUMS_TIMEOUT = 30
# A SHA256SUMS/SHA512SUMS listing is a few hundred KiB at most; refuse anything far larger.
CHECKSUMS_MAX_BYTES = 8 * 1024 * 1024
# Host -> (algorithm, checksums filename) used for the standard image URLs. An unknown host
# (a custom PYSANDBOXES_QEMU_IMAGE_URL/_BASE_URL) tries both conventions in turn.
_CHECKSUMS_BY_HOST: dict[str, tuple[str, str]] = {
    "cloud.debian.org": ("sha512", "SHA512SUMS"),
    "cloud-images.ubuntu.com": ("sha256", "SHA256SUMS"),
}
_CHECKSUM_LINE = re.compile(r"^([0-9a-fA-F]{32,})\s+\*?(.+?)\s*$")

# Complete mapping Python 3.10–3.14 → Ubuntu Cloud Image (one image per version).
# See wiki/qemu.md. Format: (release_or_codename, filename_pattern).
# Numeric keys (22.04, …) use releases/{ver}/release/; codenames use {codename}/current/.
#
# Pick a *released* image, never a development codename. Staging mounts the host's
# /lib/<triplet> over the guest (see qemu.ld_closure_libs), so the guest runs its own
# coreutils and cloud-init against the host's glibc: the guest release must therefore
# be no newer than the host. A codename tracks the devel series, which eventually
# ships a glibc the host lacks -- resolute reached 2.43 and every guest binary died
# with "version `GLIBC_2.43' not found", so the bootstrap never answered its ping.
PYTHON_VERSION_TO_UBUNTU_IMAGE: dict[tuple[int, int], tuple[str, str]] = {
    (3, 10): ("22.04", "ubuntu-22.04-server-cloudimg-{arch}.img"),
    (3, 11): ("23.04", "ubuntu-23.04-server-cloudimg-{arch}.img"),
    (3, 12): ("24.04", "ubuntu-24.04-server-cloudimg-{arch}.img"),
    (3, 13): ("25.04", "ubuntu-25.04-server-cloudimg-{arch}.img"),
    (3, 14): ("25.04", "ubuntu-25.04-server-cloudimg-{arch}.img"),
}
UBUNTU_CLOUD_RELEASES_BASE = "https://cloud-images.ubuntu.com/releases"
UBUNTU_CLOUD_IMAGES_ROOT = "https://cloud-images.ubuntu.com"
# Matches Ubuntu LTS/interim version directories under releases/ (e.g. 25.04), not codenames.
_UBUNTU_NUMERIC_RELEASE_DIR = re.compile(r"^\d+\.\d+$")

# Map platform.machine() to Debian/Ubuntu cloud image arch suffix
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


def get_standard_download_url(
    python_version: tuple[int, int] | None = None,
    arch: str | None = None,
) -> str | None:
    """Return the standard download URL for the given Python version and architecture.

    Uses Ubuntu Cloud Image for 3.10–3.14 (see PYTHON_VERSION_TO_UBUNTU_IMAGE),
    otherwise Debian Bookworm generic image. Returns None if the architecture
    is not supported.
    """
    if python_version is None:
        python_version = sys.version_info[:2]
    if arch is None:
        arch = platform.machine()
    url = get_ubuntu_image_url_for_python_version(python_version[0], python_version[1], arch)
    if url is not None:
        return url
    return get_standard_image_url(arch)


def get_default_image_filename(
    python_version: tuple[int, int] | None = None,
    arch: str | None = None,
) -> str:
    """Return the default image filename for the given Python version and architecture.

    The name is the same as the remote file (last segment of the standard download URL)
    so that a downloaded image can be reused for other purposes on the same machine.
    """
    if python_version is None:
        python_version = sys.version_info[:2]
    if arch is None:
        arch = platform.machine()
    url = get_standard_download_url(python_version, arch)
    if url:
        return url.rstrip("/").split("/")[-1]
    return f"{DEFAULT_IMAGE_PREFIX}-{python_version[0]}.{python_version[1]}-{arch}{DEFAULT_IMAGE_SUFFIX}"


def get_default_image_path(
    python_version: tuple[int, int] | None = None,
    arch: str | None = None,
) -> Path:
    """Return the default image path for the given Python version and architecture.

    The filename is the same as the one used when downloading (last segment of the
    standard URL), so the image can be reused for other needs on the same machine.

    Args:
        python_version: (major, minor) e.g. (3, 12). Defaults to sys.version_info[:2].
        arch: Architecture string e.g. x86_64, aarch64. Defaults to platform.machine().

    Returns:
        Path under get_vm_images_dir() with filename identical to the download URL
        (e.g. ubuntu-24.04-server-cloudimg-amd64.img for Python 3.12 x86_64).
    """
    if python_version is None:
        python_version = sys.version_info[:2]
    if arch is None:
        arch = platform.machine()
    dir_path = get_vm_images_dir()
    name = get_default_image_filename(python_version, arch)
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


def get_ubuntu_image_url_for_python_version(
    major: int,
    minor: int,
    arch: str | None = None,
) -> str | None:
    """Return the Ubuntu Cloud Image URL for the given Python version (3.10–3.14).

    Provides a single image per version; see PYTHON_VERSION_TO_UBUNTU_IMAGE and wiki/qemu.md.
    Returns None if the version is not in the mapping or the architecture is not supported.
    """
    key = (major, minor)
    if key not in PYTHON_VERSION_TO_UBUNTU_IMAGE:
        return None
    arch = arch or platform.machine()
    debian_arch = _ARCH_TO_DEBIAN.get(arch)
    if not debian_arch:
        return None
    release, pattern = PYTHON_VERSION_TO_UBUNTU_IMAGE[key]
    filename = pattern.format(arch=debian_arch)
    if _UBUNTU_NUMERIC_RELEASE_DIR.fullmatch(release):
        return f"{UBUNTU_CLOUD_RELEASES_BASE}/{release}/release/{filename}"
    return f"{UBUNTU_CLOUD_IMAGES_ROOT}/{release}/current/{filename}"


def _validate_download_url(url: str) -> str:
    """Validate that URL uses only http/https schemes (reject file://, etc.).

    Raises ValueError if URL uses unsafe scheme.
    """
    url_lower = url.lower().strip()
    if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
        raise ValueError(
            f"Unsafe URL scheme in image download URL. Only http:// and https:// are allowed, got: {url[:50]}"
        )
    return url


def get_download_url(path: Path) -> str | None:
    """Return the URL to use for downloading the image at path, or None if not configured.

    Uses PYSANDBOXES_QEMU_IMAGE_URL (full URL) if set, else PYSANDBOXES_QEMU_IMAGE_BASE_URL
    (base URL + path.name), else the standard download URL for the current Python version
    and arch (same filename as path.name so the image can be reused).
    """
    full = os.environ.get(ENV_VM_IMAGE_URL)
    if full and full.strip():
        return _validate_download_url(full.strip())
    base = os.environ.get(ENV_VM_IMAGE_BASE_URL)
    if base and base.strip():
        url = f"{base.strip().rstrip('/')}/{path.name}"
        return _validate_download_url(url)
    return get_standard_download_url()


_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    """Log ``message`` the first time ``key`` is seen in this process, silently after that."""
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.warning(message)


def _checksums_candidates_for_host(host: str) -> list[tuple[str, str]]:
    """Return the (algorithm, filename) pairs to try for a checksums file next to the image."""
    known = _CHECKSUMS_BY_HOST.get(host)
    if known:
        return [known]
    return [("sha256", "SHA256SUMS"), ("sha512", "SHA512SUMS")]


def _fetch_checksums_text(sums_url: str) -> str | None:
    """Download a small checksums file with the same guards as the image, or return None.

    None means "unavailable" (unreachable, wrong scheme, downgraded redirect, non-200, or
    too large), which the caller treats as "nothing to verify against", not a hard failure.
    """
    try:
        _validate_download_url(sums_url)
    except ValueError:
        return None
    try:
        req = urllib.request.Request(sums_url, headers={"User-Agent": "pysandboxes-qemu-provider/1.0"})
        with urllib.request.urlopen(req, timeout=CHECKSUMS_TIMEOUT) as resp:
            if sums_url.lower().startswith("https://") and not resp.geturl().lower().startswith("https://"):
                return None
            if resp.status != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > CHECKSUMS_MAX_BYTES:
                    logger.warning("Checksums file %s exceeds %d bytes; ignoring it", sums_url, CHECKSUMS_MAX_BYTES)
                    return None
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("Checksums file %s unreachable: %s", sums_url, e)
        return None


def _parse_checksum_line(text: str, filename: str) -> str | None:
    """Return the lowercase hex digest for filename from a ``sha256sum``/``sha512sum`` listing.

    Matches both the text-mode ``hash  name`` and the binary-mode ``hash *name`` forms.
    """
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match and match.group(2) == filename:
            return match.group(1).lower()
    return None


def _neighbor_checksum(url: str) -> tuple[str, str] | None:
    """Return (algorithm, hex_digest) for url's file name from a checksums file beside it.

    Returns None if no checksums file could be fetched and parsed for that file name.
    """
    base, sep, filename = url.rpartition("/")
    if not sep or not filename:
        return None
    host = urllib.parse.urlsplit(url).hostname or ""
    for algorithm, sums_name in _checksums_candidates_for_host(host):
        text = _fetch_checksums_text(f"{base}/{sums_name}")
        if text is None:
            continue
        digest = _parse_checksum_line(text, filename)
        if digest is not None:
            return algorithm, digest
    return None


def _resolve_expected_checksum(url: str) -> tuple[str, str] | None:
    """Return the (algorithm, hex_digest) to verify url against, or None if none is available.

    PYSANDBOXES_QEMU_IMAGE_SHA256 wins when set (no network round trip needed); otherwise a
    checksums file next to the image is tried.
    """
    pinned = os.environ.get(ENV_VM_IMAGE_SHA256, "").strip()
    if pinned:
        return "sha256", pinned.lower()
    return _neighbor_checksum(url)


def _sidecar_path(path: Path) -> Path:
    """Return the checksum sidecar path for a cached image."""
    return path.with_name(path.name + ".sha256")


def _write_sidecar(path: Path, algorithm: str, digest: str) -> None:
    """Record the verified digest, size and mtime of path so a later reuse skips re-hashing."""
    try:
        stat = path.stat()
        _sidecar_path(path).write_text(f"{algorithm}:{digest}:{stat.st_size}:{stat.st_mtime_ns}\n", encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write checksum sidecar for %s: %s", path, e)


def _sidecar_matches(path: Path) -> bool:
    """Return True if path's size and mtime still match its checksum sidecar.

    A cache hit only needs this cheap comparison; the digest itself was verified when the
    sidecar was written and is not recomputed here.
    """
    try:
        parts = _sidecar_path(path).read_text(encoding="utf-8").strip().split(":")
        if len(parts) != 4:
            return False
        stat = path.stat()
        return int(parts[2]) == stat.st_size and int(parts[3]) == stat.st_mtime_ns
    except (OSError, ValueError):
        return False


class _ChecksumMismatch(OSError):
    """Raised internally when a download's digest does not match the expected one."""


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


def _download_once(
    url: str,
    partial: Path,
    callback: Callable[[int, int | None], None],
    expected_checksum: tuple[str, str] | None,
) -> tuple[int, int | None]:
    """Stream url to partial, hashing it as it writes when expected_checksum is given.

    Returns (bytes_written, content_length_or_None). Raises OSError on a transport failure,
    a scheme-downgraded redirect, or a truncated body, and _ChecksumMismatch when the digest
    does not match expected_checksum.
    """
    logger.info("Downloading QEMU image from %s to %s", url, partial)
    digest = hashlib.new(expected_checksum[0]) if expected_checksum else None
    req = urllib.request.Request(url, headers={"User-Agent": "pysandboxes-qemu-provider/1.0"})
    # Url validated by _validate_download_url in get_download_url
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        if url.lower().startswith("https://") and not resp.geturl().lower().startswith("https://"):
            raise OSError(f"Refusing https to http redirect for {url} -> {resp.geturl()}")
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
                if digest is not None:
                    digest.update(chunk)
                size += len(chunk)
                callback(size, total_int)
    # A connection closed early is not guaranteed to raise (observed: it does not with
    # urllib/http.client, which returns the short read as a normal empty-chunk EOF).
    if total_int is not None and size != total_int:
        raise OSError(f"Download truncated: expected {total_int} bytes, got {size} for {url}")
    if digest is not None and expected_checksum is not None:
        algorithm, expected_hex = expected_checksum
        actual_hex = digest.hexdigest()
        if actual_hex.lower() != expected_hex.strip().lower():
            raise _ChecksumMismatch(
                f"Checksum mismatch downloading {url}: expected {algorithm}:{expected_hex}, got {actual_hex}"
            )
    return size, total_int


def download_image(
    path: Path,
    url: str,
    progress_callback: Callable[[int, int | None], None] | None = None,
    *,
    expected_checksum: tuple[str, str] | None = None,
) -> Path:
    """Download the image from url to path. Create parent directory if needed.

    Args:
        path: Destination file path.
        url: URL to download from.
        progress_callback: Optional (downloaded_bytes, total_bytes_or_None) called periodically.
        expected_checksum: Optional (algorithm, hex_digest), e.g. ("sha256", "ab12..."), hashed
            while streaming and compared before the rename. A mismatch is retried once (the
            upstream file may have been mid-publish), then fails closed and removes the partial.

    Returns:
        path on success.

    Raises:
        OSError: On download, write or checksum-verification failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    callback = progress_callback or _default_progress_callback
    attempts = 2 if expected_checksum is not None else 1
    for attempt in range(attempts):
        try:
            size, total_int = _download_once(url, partial, callback, expected_checksum)
        except Exception as e:
            partial.unlink(missing_ok=True)
            if isinstance(e, _ChecksumMismatch) and attempt + 1 < attempts:
                logger.warning("Retrying download of %s once after a checksum mismatch", url)
                continue
            raise OSError(f"Failed to download {url}: {e}") from e
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
    raise AssertionError("unreachable: the retry loop always returns or raises")


def ensure_image(path: Path) -> Path:
    """Return path if the image file exists and is trusted; otherwise try to download it.

    A cached image with a matching checksum sidecar (see _write_sidecar) is accepted on a
    cheap size/mtime check, no re-hash. One without a sidecar is accepted as-is (no
    retroactive verification) with a one-time warning. One whose sidecar no longer matches
    is re-downloaded and re-verified, overwriting it.

    If the file is missing (or was rejected above), get_download_url(path) is used; when a
    URL is available the image is downloaded to path. A standard (Debian/Ubuntu) URL must
    verify against a checksums file found beside it or the download is refused; a custom
    PYSANDBOXES_QEMU_IMAGE_URL/_BASE_URL verifies against PYSANDBOXES_QEMU_IMAGE_SHA256 or a
    neighbor checksums file when either is available, and otherwise downloads with a warning.

    Args:
        path: Path to the image file (typically from get_default_image_path()).

    Returns:
        path when the file exists (pre-existing or after download).

    Raises:
        FileNotFoundError: If the image does not exist and no download URL is set.
        OSError: If download or checksum verification fails.
    """
    if path.is_file():
        if _sidecar_path(path).is_file():
            if _sidecar_matches(path):
                return path
            logger.warning("Cached image %s no longer matches its checksum sidecar; re-downloading it", path)
        else:
            _warn_once(f"no-sidecar:{path}", f"Using cached image {path} without a checksum sidecar: not verified")
            return path
    url = get_download_url(path)
    if url:
        custom_url = bool(
            os.environ.get(ENV_VM_IMAGE_URL, "").strip() or os.environ.get(ENV_VM_IMAGE_BASE_URL, "").strip()
        )
        expected = _resolve_expected_checksum(url)
        if expected is None:
            if not custom_url:
                raise OSError(
                    f"No checksum could be verified for the standard image at {url}; refusing to download it "
                    f"unverified. Set {ENV_VM_IMAGE_SHA256} or place the image manually."
                )
            _warn_once(f"unverified:{url}", f"{url}: image not verified (no checksum found)")
        download_image(path, url, expected_checksum=expected)
        if expected is not None:
            _write_sidecar(path, *expected)
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


def qemu_accel_args(os_sandbox_params: Mapping[str, str]) -> list[str]:
    """Return the QEMU acceleration flags for these ``qemu.*`` parameters.

    Acceleration needs both halves: the profile asking for it and the host
    exposing ``/dev/kvm``. A container is normally not given the device, so the
    empty list -- TCG emulation -- is a working configuration, not a failure.

    Args:
        os_sandbox_params: The ``qemu.*`` rules, without their prefix.

    Returns:
        ``["-enable-kvm"]`` or an empty list.
    """
    use_kvm = str(os_sandbox_params.get("use_kvm", "true")).lower() in ("true", "1", "yes")
    return ["-enable-kvm"] if use_kvm and is_kvm_available() else []
