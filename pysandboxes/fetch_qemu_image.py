# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""CLI to prepare or fetch the default QEMU VM image for the qemu provider.

Run as: python -m pysandboxes.fetch_qemu_image

If the image is missing and PYSANDBOXES_QEMU_IMAGE_URL or PYSANDBOXES_QEMU_IMAGE_BASE_URL
is set, the image is downloaded. Otherwise prints the expected path and env var hints.
"""

import sys

from .remote.qemu_image import (
    ENV_VM_IMAGE_BASE_URL,
    ENV_VM_IMAGE_URL,
    ensure_image,
    get_default_image_path,
    get_vm_images_dir,
)


def main() -> int: #FIXME documenter
    """Print the standard image path; download the image if missing and URL is configured."""
    dir_path = get_vm_images_dir()
    default_path = get_default_image_path()
    print(f"VM images directory: {dir_path}")
    print(f"Default image path:  {default_path}")
    if default_path.is_file():
        print("\nImage already present.")
        return 0
    try:
        ensure_image(default_path)
        print("\nImage downloaded successfully.")
        return 0
    except FileNotFoundError as e:
        print(f"\n{e}")
        print(
            f"Set {ENV_VM_IMAGE_URL} (full URL) or {ENV_VM_IMAGE_BASE_URL} (base URL) to enable download."
        )
        return 1
    except OSError as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
