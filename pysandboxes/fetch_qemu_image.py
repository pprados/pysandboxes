# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""CLI to prepare or fetch the default QEMU VM image for the qemu provider.

Run as: python -m pysandboxes.fetch_qemu_image

The default image is expected at the path shown below. Place a compatible
image there (minimal Linux + Python matching host version) or set
PYSANDBOXES_VM_IMAGES_DIR to use another directory. Download from a
predefined URL is not yet implemented.
"""

from .remote.qemu_image import get_default_image_path, get_vm_images_dir


def main() -> None:
    """Print the standard image path and directory; download not implemented."""
    dir_path = get_vm_images_dir()
    default_path = get_default_image_path()
    print(f"VM images directory: {dir_path}")
    print(f"Default image path:  {default_path}")
    print()
    print(
        "Download is not yet implemented. Place a compatible QEMU image "
        "(minimal Linux + Python matching this host's version) at the path above, "
        "or set PYSANDBOXES_VM_IMAGES_DIR to use another directory. "
        "See docs for the guest image contract."
    )


if __name__ == "__main__":
    main()
