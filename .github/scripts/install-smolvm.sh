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
