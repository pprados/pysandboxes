#!/bin/sh
# Install QEMU and fetch the default VM image for the current Python version.
# Used during Docker image build (RUN after wheel install). Requires PYSANDBOXES_VM_IMAGES_DIR.
set -eux
arch=$(dpkg --print-architecture)
case "$arch" in
    amd64) qemu_pkg=qemu-system-x86 ;;
    arm64) qemu_pkg=qemu-system-aarch64 ;;
    *) echo "Unsupported arch for QEMU: $arch"; exit 1 ;;
esac
apt-get update && apt-get install -y --no-install-recommends "$qemu_pkg" qemu-utils
mkdir -p "${PYSANDBOXES_VM_IMAGES_DIR:?}"
python -m pysandboxes.fetch_qemu_image
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*
