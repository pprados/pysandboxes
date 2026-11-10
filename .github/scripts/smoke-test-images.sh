#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run by images.yml before any push. Usage: smoke-test-images.sh <version> <image tag>
# Unprivileged checks only: each image holds pysandboxes <version> and starts python-sb; each provider image has its
# binary, the qemu one its guest disk, and the smolvm one its guest archive. The container suites of the full gate test the behaviour. The qemu image also
# runs a program in its guest, behind a network rule, which loads the guest's iptables-restore against the image's
# libraries: they must be the version the guest was built with, which differs per Python version. The smolvm image runs
# its guest with no privilege, a user of the group of /dev/kvm, the device and nothing else; a failure only warns,
# as hosted runners refuse the virtio-fs shares of a guest.
set -euo pipefail

version=$1
tag=$2
engine=${CONTAINER_CMD:-docker}
kvm=${KVM_DEVICE:-/dev/kvm}

in_image() {
    local image=$1
    shift
    "$engine" run --rm "$image:$tag" "$@"
}

for image in python-sb python-sb-landlock python-sb-unshare python-sb-bwrap python-sb-qemu python-sb-qemu-microvm python-sb-gvisor python-sb-smolvm; do
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
in_image python-sb-qemu-microvm qemu-system-x86_64 --version
in_image python-sb-qemu-microvm genisoimage --version
in_image python-sb-qemu-microvm iptables-restore --version
# runsc starts from a sidecar directory that has to sit next to it: the binary alone fails at the first guest.
in_image python-sb-gvisor runsc --version
in_image python-sb-gvisor ls /usr/bin/gvisor-bin/gvisor_sentry
in_image python-sb-gvisor unshare --version
in_image python-sb-gvisor iptables-restore --version
in_image python-sb-gvisor ip -V
in_image python-sb-gvisor slirp4netns --version
in_image python-sb-smolvm smolvm --version
in_image python-sb-smolvm ls /opt/smolvm/guest.tar
# shellcheck disable=SC2016  # expanded inside the image, where the variable is set
in_image python-sb-qemu sh -c 'ls "$PYSANDBOXES_VM_IMAGES_DIR"/* >/dev/null'
in_image python-sb-qemu-microvm sh -c 'ls "$PYSANDBOXES_VM_IMAGES_DIR"/* >/dev/null'
in_image python-sb-qemu-microvm python -c 'from pysandboxes.remote.qemu_image import get_default_image_path; from pysandboxes.remote.qemu_microvm_boot import ensure_microvm_boot_artifacts; ensure_microvm_boot_artifacts(get_default_image_path(), {})'
if [[ -c $kvm ]]; then
    probe='printf "os-sandbox=qemu\nnet=ALLOW|TCP|localhost|9999|IN\n" > /tmp/probe.py-sandboxes
python-sb --pysandboxes-config=/tmp/probe.py-sandboxes -c "print(\"guest-ok\")"'
    guest=$("$engine" run --rm --privileged --device "$kvm" --group-add "$(stat -c %g "$kvm")" --network host \
        "python-sb-qemu:$tag" sh -c "$probe" 2>&1 || true)
    if [[ $guest != *guest-ok* ]]; then
        echo "::error::the qemu guest of python-sb-qemu:$tag cannot apply its network rules: $guest"
        exit 1
    fi
else
    echo "::warning::no $kvm: the qemu guest of python-sb-qemu:$tag is not run"
fi
if [[ -c $kvm ]]; then
    probe='printf "os-sandbox=qemu-microvm\\nnet=ALLOW|TCP|localhost|9999|IN\\n" > /tmp/probe.py-sandboxes
python-sb --pysandboxes-config=/tmp/probe.py-sandboxes -c "print(\"guest-ok\")"'
    guest=$("$engine" run --rm --privileged --device "$kvm" --group-add "$(stat -c %g "$kvm")" --network host \
        "python-sb-qemu-microvm:$tag" sh -c "$probe" 2>&1 || true)
    if [[ $guest != *guest-ok* ]]; then
        echo "::error::the microvm guest of python-sb-qemu-microvm:$tag cannot apply its network rules: $guest"
        exit 1
    fi
else
    echo "::warning::no $kvm: the microvm guest of python-sb-qemu-microvm:$tag is not run"
fi
if [[ -c $kvm ]]; then
    probe='printf "os-sandbox=smolvm\\n" > /tmp/probe.py-sandboxes
python-sb --pysandboxes-config=/tmp/probe.py-sandboxes -c "print(\"guest-ok\")"'
    guest=$("$engine" run --rm --device "$kvm" --group-add "$(stat -c %g "$kvm")" --user "$(id -u):$(id -g)" \
        "python-sb-smolvm:$tag" sh -c "$probe" 2>&1 || true)
    if [[ $guest != *guest-ok* ]]; then
        echo "::warning::the smolvm guest of python-sb-smolvm:$tag did not run on this runner (virtio-fs shares fail on hosted runners; checked locally before a release): $guest"
    fi
else
    echo "::warning::no $kvm: the smolvm guest of python-sb-smolvm:$tag is not run"
fi
echo "The eight images hold pysandboxes $version"
