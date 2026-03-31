#!/usr/bin/env bash
# Strong typing and rigor for Python contributors (pprados)
set -euo pipefail

# FIXME: s'assurer de la nécessité d'accorder  NET_ADMIN dans le yaml
# --- Configuration ---
POD_NAME="pysandboxes-test"
MANIFEST="scripts/kube-pysandboxes.yaml"

# --- Cleanup Logic ---
# On s'assure que le mount s'arrête ET que le pod est supprimé à la sortie
MINIKUBE_PID=""
cleanup() {
    echo -e "\n--- Cleaning up resources ---"
    if [ -n "$MINIKUBE_PID" ]; then
        echo "Stopping minikube mount (PID: $MINIKUBE_PID)..."
        kill "$MINIKUBE_PID" || true
    fi
    echo "Deleting pod $POD_NAME..."
    kubectl delete pod "$POD_NAME" --ignore-not-found --now || true
}
trap cleanup EXIT

# --- Execution ---

echo "Starting minikube mount in background..."
minikube mount .:/mnt/pysandboxes &
MINIKUBE_PID=$!

echo "Applying Kubernetes manifest..."
kubectl apply -f "$MANIFEST"

echo "Waiting for pod $POD_NAME to be ready..."
# On attend que le pod soit au moins initialisé et prêt pour le exec
kubectl wait --for=condition=Ready pod/"$POD_NAME" --timeout=60s

TIMEOUT="${TIMEOUT:-50}"

echo "Executing tests inside the pod (timeout: ${TIMEOUT}s)..."
rc=0
timeout --foreground "$TIMEOUT" kubectl exec -it "$POD_NAME" -- /bin/bash -c "
    # Verify /dev/net/tun is available (required by slirp4netns)
    if [ ! -c /dev/net/tun ]; then
        echo 'ERROR: /dev/net/tun not available. Check pod volume mounts.'
        exit 1
    fi
    apt-get update && \
    apt-get install -y libvirt-dev pkg-config iptables iproute2 slirp4netns && \
    PYTHONUNBUFFERED=1 pip install --progress-bar on -e . && \
    PYTHONUNBUFFERED=1 OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
" || rc=$?
if [ $rc -eq 124 ]; then
    echo "ERROR: Test execution timed out after ${TIMEOUT}s"
    exit 1
fi
exit $rc

# Note: Le "kubectl delete" sera appelé automatiquement par le trap EXIT ici.