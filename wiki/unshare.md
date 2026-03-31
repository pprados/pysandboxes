# Unshare

Unshare is a user-space container technology that allows programs to be launched in isolation from the rest of the system, with a **user stack IP**. It enables limiting disk access, network access, system calls, and more. For more information, consult the [documentation](https://man7.org/linux/man-pages/man2/unshare.2.html).

Root privileges are not required to add firewall rules.

## Prerequisites

To use the unshare technology, you must install [slirp4netns](https://manpages.debian.org/experimental/slirp4netns/slirp4netns.1.en.html), [iptables](https://man7.org/linux/man-pages/man8/iptables.8.html) and set `kernel.unprivileged_userns_clone` to `1` (Normally, this is enabled by default.).

```bash
# Check permissions
sysctl kernel.unprivileged_userns_clone
sysctl kernel.apparmor_restrict_unprivileged_userns

# Set permissions
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1

# Install slirp4netns and iptables
sudo apt install slirp4netns iptables
```

## Execution Model

During launch, a local `root` user within the sandbox is used for code execution. This user has no privileges once directory mounts and iptables rules have been activated.

> **Note:** Some applications may behave differently when running as the 'root' user.


## Use inside Docker
The unshare technology is compatible with 
```bash
docker run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    bash

apt update && apt install -y libvirt-dev pkg-config iptables && pip install .
```

or podman:

```bash
podman run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    bash

apt update && apt install -y libvirt-dev pkg-config iptables && pip install .
```

## Kubernetes

```bash
minikube mount .:/mnt/pysandboxes &
kubectl apply -f kube-pysandboxes.yaml
kubectl delete pod pysandboxes-test
```
