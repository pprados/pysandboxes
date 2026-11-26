#!/bin/bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Run the docker-sandbox provider inside a container: sbx daemon, login, guest template, then tst_usage.
# Meant for the image python-sb-docker-sandbox, started with --privileged --device /dev/kvm, the sbx binaries mounted
# from the host and the repository mounted at /app. DOCKER_USER and DOCKER_PAT (an access token) come from the caller.
set -euo pipefail

: "${DOCKER_USER:?DOCKER_USER is required}"
: "${DOCKER_PAT:?DOCKER_PAT is required}"
PROFILE=tests/integration_tests/py-sandbox-test.profile

# The daemon of sbx takes a loop device for each image layer, and a container has no udev to create the nodes.
for i in $(seq 0 255); do [ -e "/dev/loop$i" ] || mknod "/dev/loop$i" b 7 "$i"; done

# What an earlier row left, root-owned, in the mounted tree must not stop this one.
mkdir -p /app/tmp && rm -f /app/tmp/test.remove
chmod -R a+rwX /app/tmp 2>/dev/null || true

(sbx daemon start >/tmp/sbxd.log 2>&1 &)
for _ in $(seq 1 30); do sbx daemon status 2>&1 | grep -q running && break; sleep 1; done
sbx daemon status 2>&1 | grep -q running || { echo "sbx daemon did not start"; tail -20 /tmp/sbxd.log; exit 1; }

printf '%s' "$DOCKER_PAT" | sbx login --username "$DOCKER_USER" --password-stdin >/dev/null
sbx --no-input policy init deny-all >/dev/null

VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
mapfile -t DEPS < <(python -c 'import tomllib; print(chr(10).join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))')
scripts/build_docker_sandbox_template.sh "$VERSION" "${DEPS[@]}"

for py_sandbox in True False; do
  echo "--- tst_usage with --py-sandbox=$py_sandbox"
  PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 OS_SANDBOX=docker-sandbox My_ENV=1 \
    python-sb --py-sandbox="$py_sandbox" --pysandboxes-config="$PROFILE" -m tests.integration_tests.tst_usage
done
