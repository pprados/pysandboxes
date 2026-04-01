#!/usr/bin/env bash
# Kubernetes pod test for pysandboxes (minikube + docker-env).
set -euo pipefail

PYTHON_SB_ARGS="--py-sandbox=false --pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

# --- Configuration ---
POD_NAME="pysandboxes-test"
IMAGE_NAME="python-sb:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFEST="$SCRIPT_DIR/kube-pysandboxes.yaml"

# --- Cleanup Logic ---
# Ensure the mount process is stopped and the pod is deleted on exit
MINIKUBE_PID=""
cleanup() {
    echo -e "\n--- Cleaning up resources ---"
    if [ -n "$MINIKUBE_PID" ]; then
        echo "Stopping minikube mount (PID: $MINIKUBE_PID)..."
        kill "$MINIKUBE_PID" || true
    fi
    echo "Deleting pod $POD_NAME..."
    kubectl delete pod "$POD_NAME" --ignore-not-found --now 2>/dev/null || true
}
trap cleanup EXIT

# --- Execution ---

# Ensure minikube is running (avoids "proto: cannot parse invalid wire-format data")
if ! minikube status >/dev/null 2>&1; then
    echo "ERROR: minikube is not running. Start it with: minikube start"
    exit 1
fi

# Build image in minikube's Docker daemon if missing (build-image-docker uses docker only, not podman)
if ! (eval "$(minikube docker-env)" && docker image inspect "$IMAGE_NAME" >/dev/null 2>&1); then
    echo "Image $IMAGE_NAME not found in minikube, building with make build-image-docker..."
    eval "$(minikube docker-env)" && (cd "$ROOT_DIR" && make build-image-docker)
fi

echo "Starting minikube mount in background..."
# Redirect stderr to hide "Exiting due to MK_INTERRUPTED" when killed in cleanup (expected)
minikube mount "$ROOT_DIR":/mnt/pysandboxes 2>/dev/null &
MINIKUBE_PID=$!
# Allow the mount to settle before the pod mounts hostPath /mnt/pysandboxes
sleep 3

echo "Applying Kubernetes manifest..."
kubectl apply -f "$MANIFEST"

echo "Waiting for pod $POD_NAME to be ready..."
# Wait until the pod is at least initialized and ready for exec (image = python-sb:latest, matches build)
WAIT_TIMEOUT="${WAIT_TIMEOUT:-120}"
if ! kubectl wait --for=condition=Ready pod/"$POD_NAME" --timeout="${WAIT_TIMEOUT}s"; then
    echo "ERROR: Pod did not become Ready in ${WAIT_TIMEOUT}s. Pod status:"
    kubectl get pod "$POD_NAME" -o wide 2>/dev/null || true
    kubectl describe pod "$POD_NAME" 2>/dev/null | tail -30
    exit 1
fi

TIMEOUT="${TIMEOUT:-120}"

echo "Executing tests inside the pod (timeout: ${TIMEOUT}s)..."
# Image python-sb:latest already has deps (libvirt-dev, slirp4netns, etc.); reinstall from mount for up-to-date code
rc=0
timeout --foreground "$TIMEOUT" kubectl exec -it "$POD_NAME" -- /bin/bash -c "
    if [ ! -c /dev/net/tun ]; then
        echo 'ERROR: /dev/net/tun not available. Check pod volume mounts.'
        exit 1
    fi
    pip install --no-cache-dir -e . &&
    PYTHONUNBUFFERED=1 TERM=\${TERM:-xterm} OS_SANDBOX=unshare python-sb $PYTHON_SB_ARGS -m tests.integration_tests.tst_usage
" || rc=$?
if [ $rc -eq 124 ]; then
    echo "ERROR: Test execution timed out after ${TIMEOUT}s"
    exit 1
fi

echo "--- Pod logs (container stdout/stderr) ---"
kubectl logs "$POD_NAME" 2>/dev/null || true

echo "********* Kubernetes pod test complete *********"

exit $rc

# Note: kubectl delete is invoked automatically by the EXIT trap above.