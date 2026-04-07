# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU VM image directory and KVM detection helpers for the qemu provider.

Provides resolution of the standard VM images directory (XDG-compliant),
default image path by Python version and architecture, and KVM availability check.
"""

import logging
import os
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_VM_IMAGES_DIR = "PYSANDBOXES_VM_IMAGES_DIR"
XDG_DATA_HOME = "XDG_DATA_HOME"
DEFAULT_VM_IMAGES_SUBDIR = "vm-images"
DEFAULT_IMAGE_PREFIX = "pysandboxes-python"
DEFAULT_IMAGE_SUFFIX = ".qcow2"


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


def ensure_image(path: Path) -> Path:
    """Return path if the image file exists; otherwise raise with a clear message.

    Does not download. First version: callers should use fetch_qemu_image or
    provide the image manually. See docs for standard directory layout.

    Args:
        path: Path to the image file (typically from get_default_image_path()).

    Returns:
        path if path.exists() and path.is_file().

    Raises:
        FileNotFoundError: If the image file does not exist, with a message
            pointing to the fetch command or documentation.
    """
    if path.is_file():
        return path
    dir_path = path.parent
    msg = (
        f"QEMU image not found: {path}. "
        f"Place the image in the standard directory {dir_path!s} or set {ENV_VM_IMAGES_DIR}. "
        "Run `python -m pysandboxes.fetch_qemu_image` to download (when available), "
        "or see docs for the guest image contract and standard directory layout."
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
