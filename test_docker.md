apt install -y build-essential

# Avec build-essential et reseau
docker run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    bash

apt update && apt install -y libvirt-dev pkg-config iptables && pip install .

python-sb -m tests.integration_tests.tst_usage


# Kube

```bash
minikube mount .:/mnt/pysandboxes &
kubectl apply -f kube-pysandboxes.yaml
kubectl delete pod pysandboxes-test
```
