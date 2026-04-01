#!/usr/bin/env bash
# Run tests with pre-built image python-sb:latest (python-sb directly, no apt/pip at runtime).
# Builds the image if missing. Used by test-docker.sh via DOCKER_CMD=docker.
set -euo pipefail

DOCKER_CMD="${DOCKER_CMD:-podman}"
IMAGE_NAME="python-sb:latest"
OS_SANDBOX="${OS_SANDBOX:-unshare}"
PYTHON_SB_ARGS="--py-sandbox=false --pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if ! $DOCKER_CMD image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "Image $IMAGE_NAME not found, building with make build-image..."
  (cd "$ROOT_DIR" && make build-image)
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

# OS_SANDBOX=unshare does nested unshare(2) + mount(2) of /proc; requires --privileged on most hosts.
$DOCKER_CMD run $TTY_FLAGS --rm \
  --network bridge \
  --privileged \
  "${VOLUME_MOUNT[@]}" \
  -w /app \
  "$IMAGE_NAME" \
  sh -c "${DOCKER_PREFIX} $PIP_INSTALL && \
    cd /app && \
    OS_SANDBOX=$OS_SANDBOX My_ENV=1 \
    python-sb \
    $PYTHON_SB_ARGS \
    -m tests.integration_tests.tst_usage"
echo "********* $DOCKER_CMD test terminate *********"
