#!/usr/bin/env bash
# Run tests with pre-built image pysandboxes:latest (python-sb directly, no apt/pip at runtime).
# Builds the image if missing. Used by test-docker.sh via DOCKER_CMD=docker.
set -euo pipefail

DOCKER_CMD="${DOCKER_CMD:-podman}"
IMAGE_NAME="pysandboxes:latest"
OS_SANDBOX="${OS_SANDBOX:-unshare}"
#PYTHON_SB_ARGS="${OS_SANDBOX:- --py-sandbox=false}"
PYTHON_SB_ARGS="--py-sandbox=false"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if ! $DOCKER_CMD image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "Image $IMAGE_NAME not found, building from Dockerfile..."
  (cd "$ROOT_DIR" && $DOCKER_CMD build -t "$IMAGE_NAME" -f Dockerfile .)
fi

# Use -it only when stdin is a TTY (Docker fails with "not a TTY" otherwise; Podman only warns).
TTY_FLAGS=""
[ -t 0 ] && TTY_FLAGS="-it"

# With Docker, the unshare child often cannot see the bind-mounted /app in its mount namespace,
# so the editable install is invisible there. Use a regular install so the package lives in
# site-packages (container fs) and is visible to the unshare child. Podman keeps /app visible.
# Ensure /app is readable by the unshare child (mapped user) so env --chdir=/app works.
if [ "$DOCKER_CMD" = "docker" ]; then
  PIP_INSTALL="pip install ."
  VOLUME_MOUNT=(-v "$(pwd)":/app)
  # Unshare child may run as mapped user; make /app readable and /app/tmp writable for tests
  DOCKER_PREFIX="chmod -R a+rX /app && mkdir -p /app/tmp && chmod -R a+rwX /app/tmp &&"
else
  PIP_INSTALL="pip install -e ."
  VOLUME_MOUNT=(-v "$(pwd)":/app)
  DOCKER_PREFIX=""
fi

$DOCKER_CMD run $TTY_FLAGS --rm \
  --network bridge \
  --privileged \
  "${VOLUME_MOUNT[@]}" \
  -w /app \
  "$IMAGE_NAME" \
  sh -c "${DOCKER_PREFIX} $PIP_INSTALL && \
    OS_SANDBOX=$OS_SANDBOX \
    python-sb $PYTHON_SB_ARGS \
    -m tests.integration_tests.tst_usage"
echo "********* $DOCKER_CMD test terminate ********* \n"
