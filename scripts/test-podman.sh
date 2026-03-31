#!/usr/bin/env bash
# TODO: tester également avec un dockerfile
set -euo pipefail

podman \
run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    sh -c 'apt update && \
      apt install -y libvirt-dev pkg-config iptables iproute2 slirp4netns &&
      pip install -e . && \
      OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage'
