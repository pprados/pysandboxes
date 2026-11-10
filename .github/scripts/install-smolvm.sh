#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
#
# Installs the smolvm release that Dockerfile-smolvm pins, after checking its SHA-256, and builds the guest archive for
# the Python of the run (UV_PYTHON), where tests/integration_tests/_env.py and the samples look for it.
# Run by integration.yml and samples.yml from the root of the repository, on a Linux x86_64 runner.
set -euo pipefail

version=$(sed -n 's/^ARG SMOLVM_VERSION=//p' Dockerfile-smolvm)
sha256=$(sed -n 's/^ARG SMOLVM_SHA256=//p' Dockerfile-smolvm)
archive="${RUNNER_TEMP:-/tmp}/smolvm.tar.gz"

curl -fsSL -o "$archive" \
    "https://github.com/smol-machines/smolvm/releases/download/v${version}/smolvm-${version}-linux-x86_64.tar.gz"
echo "${sha256}  ${archive}" | sha256sum -c -
sudo mkdir -p /opt/smolvm
sudo tar -xzf "$archive" --strip-components=1 -C /opt/smolvm
sudo ln -sf /opt/smolvm/smolvm /usr/local/bin/smolvm
smolvm --version

make -o uv.lock build-smolvm-guest

# Fail here, with what is needed to understand it, rather than in every smolvm test: the runner's kernel and
# filesystems differ from a workstation's, and a guest that cannot start says so only in the debug log of smolvm.
guest=$(ls build/smolvm-guest-*.tar | head -n 1)
log="${RUNNER_TEMP:-/tmp}/smolvm-check.log"
{
    echo "host: $(uname -sr), $(stat -f -c '%T' "$HOME") under HOME, $(stat -f -c '%T' /tmp) under /tmp"
    ls -l /dev/kvm
    lscpu | grep -i -e 'hypervisor' -e 'virtualization' || true
} >&2
if ! guest_kernel=$(RUST_LOG=debug smolvm machine run --image "$guest" -- uname -sr 2>"$log"); then
    echo "::error::the smolvm guest does not start on this runner"
    cat "$log" >&2
    exit 1
fi
echo "guest: $guest_kernel"

# What python-sb adds to that command, one option at a time: the first failure of a test run names the option.
probe=$(mktemp -d)
for option in "-v $probe:/mnt/probe:ro" "-v $probe:/mnt/probe" "-v $PWD:/mnt/probe:ro" "--expose-socket /tmp/probe.sock:$probe/probe.sock"; do
    if smolvm machine run --image "$guest" $option -- true 2>"$log"; then
        echo "smolvm option ok: $option" >&2
    else
        echo "smolvm option FAILS: $option: $(tail -n 1 "$log")" >&2
    fi
done
