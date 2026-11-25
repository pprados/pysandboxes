#!/bin/bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Build the guest template of the docker-sandbox provider: pysandboxes-guest:<python minor>.
# The template holds the interpreter and the dependencies of pysandboxes; the package itself is mounted by the provider.
# Usage: build_docker_sandbox_template.sh <python minor, e.g. 3.15> <dependency>...
set -euo pipefail

VERSION=$1
shift
TAG="pysandboxes-guest:${VERSION}"
NAME="pysb-build-$$"
ALLOWED="pypi.org,files.pythonhosted.org,github.com,**.github.com,**.githubusercontent.com"

cleanup() { sbx rm --force "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

sbx create shell --name "$NAME" --no-progress
sbx policy allow network --sandbox "$NAME" "$ALLOWED" >/dev/null
sbx exec -u root "$NAME" sh -c "
  set -e
  UV_PYTHON_INSTALL_DIR=/usr/local/uv-python uv python install ${VERSION}
  ln -sfn \"\$(UV_PYTHON_INSTALL_DIR=/usr/local/uv-python uv python find ${VERSION})\" /usr/local/bin/python
  /usr/local/bin/python -c 'import sys; print(sys.version)'
  uv pip install --python /usr/local/bin/python --break-system-packages $(printf '%q ' "$@")
  ln -sf /etc/ssl/certs/ca-certificates.crt /etc/ssl/cert.pem
  rm -f /usr/bin/sudo
"
sbx policy rm network --sandbox "$NAME" --resource "$ALLOWED" >/dev/null 2>&1 || true
printf "y\n" | script -qec "sbx template save $NAME $TAG" /dev/null
echo "docker-sandbox template ready: $TAG"
