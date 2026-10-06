#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run by the images job of release.yml before any push. Usage: smoke-test-images.sh <version> <image tag>
# Unprivileged checks only: each image holds pysandboxes <version> and starts python-sb; each provider image has its
# binary, and the qemu one its guest disk. The container suites of the full gate test the behaviour.
set -euo pipefail

version=$1
tag=$2
engine=${CONTAINER_CMD:-docker}

in_image() {
    local image=$1
    shift
    "$engine" run --rm "$image:$tag" "$@"
}

for image in python-sb python-sb-landlock python-sb-unshare python-sb-bwrap python-sb-qemu; do
    held=$(in_image "$image" python -c "import importlib.metadata as m; print(m.version('pysandboxes'))")
    if [[ $held != "$version" ]]; then
        echo "::error::$image:$tag holds pysandboxes $held, expected $version"
        exit 1
    fi
    in_image "$image" python-sb --help >/dev/null
done
in_image python-sb-unshare unshare --version
in_image python-sb-unshare iptables --version
in_image python-sb-unshare iptables-restore --version
in_image python-sb-unshare ip -V
in_image python-sb-unshare slirp4netns --version
in_image python-sb-bwrap bwrap --version
in_image python-sb-bwrap iptables-restore --version
in_image python-sb-bwrap slirp4netns --version
in_image python-sb-bwrap nsenter --version
in_image python-sb-qemu qemu-system-x86_64 --version
in_image python-sb-qemu genisoimage --version
in_image python-sb-qemu iptables-restore --version
# shellcheck disable=SC2016  # expanded inside the image, where the variable is set
in_image python-sb-qemu sh -c 'ls "$PYSANDBOXES_VM_IMAGES_DIR"/* >/dev/null'
echo "The five images hold pysandboxes $version"
