#!/usr/bin/env bash
# Run tests with pre-built image pysandboxes:ready (python-sb directly, no apt/pip at runtime).
# Builds the image if missing. Used by test-docker.sh via DOCKER_CMD=docker.
set -euo pipefail

DOCKER_CMD="${DOCKER_CMD:-podman}"
IMAGE_NAME="pysandboxes:ready"
OS_SANDBOX="${OS_SANDBOX:-unshare}"
#PYTHON_SB_ARGS="${OS_SANDBOX:- --py-sandbox=false}"
PYTHON_SB_ARGS="--py-sandbox=false"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if ! $DOCKER_CMD image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "Image $IMAGE_NAME not found, building from Dockerfile..."
  (cd "$ROOT_DIR" && $DOCKER_CMD build -t "$IMAGE_NAME" -f Dockerfile .)
fi

$DOCKER_CMD run -it --rm \
  --network bridge \
  --privileged \
  -v "$(pwd)":/app \
  -w /app \
  "$IMAGE_NAME" \
  sh -c "pip install -e . && \
    OS_SANDBOX=$OS_SANDBOX \
    python-sb $PYTHON_SB_ARGS \
    -m tests.integration_tests.tst_usage"
