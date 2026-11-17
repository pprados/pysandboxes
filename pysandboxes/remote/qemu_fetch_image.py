# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""CLI to prepare, fetch or migrate the QEMU VM images for the qemu provider.

Run as: python -m pysandboxes.remote.qemu_fetch_image [--migrate-cache]

With no option: if the default image is missing and PYSANDBOXES_QEMU_IMAGE_URL or
PYSANDBOXES_QEMU_IMAGE_BASE_URL is set, it is downloaded. Otherwise prints the expected
path and env var hints.

--migrate-cache: verifies every cached image in the VM images directory that has no
checksum sidecar yet (e.g. downloaded before the checksum feature existed) against its
own upstream checksums, and writes the sidecar on a match. Never downloads or modifies
an image; a mismatch or an unreachable checksums file is reported and left as it was.
"""

import argparse
import sys

from .qemu_image import (
    ENV_VM_IMAGE_BASE_URL,
    ENV_VM_IMAGE_URL,
    ensure_image,
    get_default_image_path,
    get_vm_images_dir,
    migrate_image_cache,
)


def _migrate_cache() -> int:
    """Verify every unverified cached image and report what each one became."""
    results = migrate_image_cache()
    if not results:
        print("No cached image without a checksum sidecar.")
        return 0
    failures = 0
    for path, outcome in results.items():
        print(f"{path.name}: {outcome}")
        if outcome != "verified":
            failures += 1
    if failures:
        print(f"\n{failures} of {len(results)} image(s) could not be verified; see wiki/qemu.md.")
    return 1 if failures else 0


def main() -> int:
    """Print the standard image path and download it, or migrate the whole image cache."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--migrate-cache",
        action="store_true",
        help="verify every cached image without a checksum sidecar and write one on a match",
    )
    args = parser.parse_args()

    if args.migrate_cache:
        return _migrate_cache()

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
        print(f"Set {ENV_VM_IMAGE_URL} (full URL) or {ENV_VM_IMAGE_BASE_URL} (base URL) to enable download.")
        return 1
    except OSError as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
