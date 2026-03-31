# TODO: sheban et repertoire de kub-pysandboxes et flag rigeur. utiliser uvx ?
set -euo pipefail

minikube mount .:/mnt/pysandboxes &
kubectl apply -f scripts/kube-pysandboxes.yaml
# kubectl exec -it pysandboxes-test -- /bin/bash
kubectl delete pod pysandboxes-test

# apt update && \
      apt install -y libvirt-dev pkg-config iptables iproute2 slirp4netns &&
      pip install -e . && \
      OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage