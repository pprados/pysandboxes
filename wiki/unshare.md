# Unshare

Unshare is a user-space containerization technology that allows programs to run in isolation from the rest of the system, featuring a **user-mode network stack**. It enables restrictions on disk access, network usage and more. For further details, consult the [documentation](https://man7.org/linux/man-pages/man2/unshare.2.html).

Root privileges are not required to configure firewall rules within the namespace.

## Prerequisites

### userns clone
To utilize unshare, you must install [slirp4netns](https://manpages.debian.org/experimental/slirp4netns/slirp4netns.1.en.html) and [iptables](https://man7.org/linux/man-pages/man8/iptables.8.html), and ensure `kernel.unprivileged_userns_clone` is set to `1` (this is typically enabled by default).

```bash
# Verify permissions
sudo sysctl kernel.unprivileged_userns_clone  # Must be 1
sudo sysctl kernel.apparmor_restrict_unprivileged_userns # Must be 0

# Configure permissions
sudo sysctl -w kernel.unprivileged_userns_clone=1
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# Permanently configure permissions
echo -e "kernel.unprivileged_userns_clone = 1
kernel.apparmor_restrict_unprivileged_userns = 0" | sudo tee /etc/sysctl.d/99-userns.conf > /dev/null
sudo sysctl -p /etc/sysctl.d/99-userns.conf

# Check
unshare -U -r /bin/sh -c "whoami"

# Install slirp4netns and iptables
sudo apt install slirp4netns iptables
```

### AppArmor

Check the privileged
```
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```
```
echo "kernel.apparmor_restrict_unprivileged_userns = 0" | sudo tee /etc/sysctl.d/60-apparmor-unprivileged.conf
```
## Execution Model

When launched, code execution occurs as a local `root` user within the sandbox. This user retains no elevated privileges on the host system once directory mounts and iptables rules are active.

> **Note:** Some applications may behave differently when running as the 'root' user.

## Usage inside Docker

Unshare is compatible with Docker, though it requires elevated privileges.

```bash
docker \
  run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    sh -c 'apt update && \
      apt install -y libvirt-dev pkg-config iptables iproute2 slirp4netns &&
      pip install -e . && \
      OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage'
```
The `scripts/test-kubernetes.sh` script provides a usage example.

## Usage inside Podman

Unshare is compatible with Podman, though it requires elevated privileges.

```bash
podman \
  run -it --rm \
    --privileged \
    --network bridge \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11 \
    sh -c 'apt update && \
      apt install -y libvirt-dev pkg-config iptables iproute2 slirp4netns &&
      pip install -e . && \
      OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage'
```

## Kubernetes

Example YAML configuration:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pysandboxes-test
spec:
  containers:
    - name: pysandboxes-test
      image: python:latest
      workingDir: /app
      securityContext:
        capabilities:
          add:
            - SYS_ADMIN    # Allows unshare (namespace creation)
            - NET_ADMIN    # Allows network configuration (ip link, etc.)
        seccompProfile:
          type: Unconfined # Disables the filter blocking unshare
      command: [ "/bin/sh", "-c" ] # Keeps the pod alive
      args:
        - |
          apt update && \
          apt install -y libvirt-dev pkg-config iptables iproute2 slirp4netns && \
          pip install -e . && \
          OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
      volumeMounts:
        - name: code-local
          mountPath: /app          # Path inside the Pod
        - name: dev-net-tun
          mountPath: /dev/net/tun  # Required by slirp4netns
  volumes:
    - name: code-local
      hostPath:
        path: /mnt/pysandboxes
        type: Directory
    - name: dev-net-tun
      hostPath:
        path: /dev/net/tun
        type: CharDevice
```

Note the restrictions lifted to enable unshare usage within a pod:
```yaml
      securityContext:
        capabilities:
          add:
            - SYS_ADMIN    # Allows unshare (namespace creation)
            - NET_ADMIN    # Allows network configuration (ip link, etc.)
        seccompProfile:
          type: Unconfined # Disables the filter blocking unshare
```

The `scripts/test-kubernetes.sh` script demonstrates this usage.

```bash
minikube mount .:/mnt/pysandboxes &
kubectl apply -f kube-pysandboxes.yaml
kubectl delete pod pysandboxes-test
```