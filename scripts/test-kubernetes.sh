#!/usr/bin/env bash
# Strong typing and rigor for Python contributors (pprados)
set -euo pipefail

# FIXME: s'assurer de la nécessité d'accorder  NET_ADMIN dans le yaml
# --- Configuration ---
POD_NAME="pysandboxes-test"
MANIFEST="scripts/kube-pysandboxes.yaml"
IMAGE_NAME="pysandboxes:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

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
    kubectl delete pod "$POD_NAME" --ignore-not-found --now 2>/dev/null || true
}
trap cleanup EXIT

# --- Execution ---

# Vérifier que minikube est démarré (évite "proto: cannot parse invalid wire-format data")
if ! minikube status >/dev/null 2>&1; then
    echo "ERROR: minikube is not running. Start it with: minikube start"
    exit 1
fi

# Construire l'image enrichie (même que test-podman.sh) dans le daemon Docker de minikube si absente
if eval "$(minikube docker-env)" && docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Image $IMAGE_NAME already present in minikube, skipping build."
else
    echo "Building image $IMAGE_NAME inside minikube..."
    eval "$(minikube docker-env)" && (cd "$ROOT_DIR" && docker build -t "$IMAGE_NAME" -f Dockerfile .)
fi

echo "Starting minikube mount in background..."
# Rediriger stderr pour masquer "Exiting due to MK_INTERRUPTED" lors du kill en cleanup (comportement normal)
minikube mount .:/mnt/pysandboxes 2>/dev/null &
MINIKUBE_PID=$!
# Laisser le mount s'établir avant que le pod monte hostPath /mnt/pysandboxes
sleep 3

echo "Applying Kubernetes manifest..."
kubectl apply -f "$MANIFEST"

echo "Waiting for pod $POD_NAME to be ready..."
# On attend que le pod soit au moins initialisé et prêt pour le exec (image = pysandboxes:latest, aligné avec le build)
WAIT_TIMEOUT="${WAIT_TIMEOUT:-120}"
if ! kubectl wait --for=condition=Ready pod/"$POD_NAME" --timeout="${WAIT_TIMEOUT}s"; then
    echo "ERROR: Pod did not become Ready in ${WAIT_TIMEOUT}s. Pod status:"
    kubectl get pod "$POD_NAME" -o wide 2>/dev/null || true
    kubectl describe pod "$POD_NAME" 2>/dev/null | tail -30
    exit 1
fi

TIMEOUT="${TIMEOUT:-120}"

echo "Executing tests inside the pod (timeout: ${TIMEOUT}s)..."
# Image pysandboxes:latest a déjà les deps (libvirt-dev, slirp4netns, etc.) ; on réinstalle depuis le montage pour le code à jour
rc=0
timeout --foreground "$TIMEOUT" kubectl exec -it "$POD_NAME" -- /bin/bash -c "
    if [ ! -c /dev/net/tun ]; then
        echo 'ERROR: /dev/net/tun not available. Check pod volume mounts.'
        exit 1
    fi
    pip install --no-cache-dir -e . && \
    PYTHONUNBUFFERED=1 TERM=\${TERM:-xterm} OS_SANDBOX=unshare python-sb --py-sandbox=false -m tests.integration_tests.tst_usage
" || rc=$?
if [ $rc -eq 124 ]; then
    echo "ERROR: Test execution timed out after ${TIMEOUT}s"
    exit 1
fi

echo "--- Pod logs (container stdout/stderr) ---"
kubectl logs "$POD_NAME" 2>/dev/null || true

echo "********* Kubernetes pod test terminate *********\n"

exit $rc

# Note: Le "kubectl delete" sera appelé automatiquement par le trap EXIT ici.