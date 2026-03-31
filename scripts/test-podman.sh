# TODO: tester également avec un dockerfile
podman \
run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    sh -c 'apt update && \
      apt install -y libvirt-dev pkg-config iptables iproute2 dnsutils &&
      pip install -e . && \
      bash

echo \
      OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage'

# Note: purger l'installer au strict nécessaire. dnsutils à virer