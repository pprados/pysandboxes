# libkrun

The `libkrun` provider runs the sandbox in a KVM micro-VM. There is no disk image and no cloud-init: the guest kernel
boots in tens of milliseconds, mounts the host root read-only through virtio-fs, and starts the host's own
interpreter. A whole run takes about a second, against 20 to 40 seconds for [`qemu`](qemu.md).

```python
from pysandboxes.sandboxes_api import sandboxes

with sandboxes(os_sandbox="libkrun"):
    ...  # runs in the micro-VM
```

## Prerequisites

- Linux (or WSL) with read/write access to `/dev/kvm`.
- `libkrun.so` and `libkrunfw.so` installed on the host.
- For a profile with an outgoing `net=` rule: `unshare`, `slirp4netns`, `iptables-restore`, `ip` and `passt`.

`unavailable_reason()` checks the first two and the provider says which one is missing. The interpreter needs no `AF_VSOCK` support: the guest creates its vsock socket through libc (`ctypes`).

## How it works

- **Channel.** libkrun relays a Unix socket the host binds to a vsock port of the guest. A shim started by the guest, under the host's interpreter, listens on that vsock port and relays to the Unix socket of the sandbox daemon. The host waits for the
  shim's ready file before it connects: libkrun aborts when a host connection reaches a port nobody listens on.
  `remote-endpoint=tcp` or a fixed `port=` cannot work with this provider.
- **Files.** The root is shared read-only. A directory named by `expose-ro=` or `expose-rw=` gets its own virtio-fs
  share, because the guest mounts a private `/tmp`. A read-only share is enforced by the VMM (`EROFS`).
- **Environment.** The guest command starts with `env -i`: it receives the variables the rules allow and nothing else.
- **Network.** Without an outgoing `net=ALLOW` rule the guest has no network device: only its loopback exists, and the
  host sees no connection, whatever the guest does. With one, the guest gets a virtio NIC whose other end is `passt`,
  started in a private user and network namespace where the host loads an `iptables` filter built from the `net=`
  rules (the same translation as `unshare` and `gvisor`) and attaches `slirp4netns`. Every connection `passt` opens
  crosses that filter, so native code in the guest cannot walk around the Python guard. The micro-VM itself stays
  outside the namespace: libkrun does not boot inside a user namespace.
- **Exit code.** A micro-VM that ends without the guest reporting an exit code is a failure (70), never a success.

## Limitations

- **The whole host root is readable in the guest.** The root is shared read-only, so every file the user can read is
  readable in the guest, whatever the `expose-ro=` rules say; `ignore=` is enforced by the Python guard only. A rule
  confines writes and adds writable shares, it does not hide a path. Do not run untrusted native code that must not
  see the host's files: use `bwrap` or `unshare`, which hide them. See [weaknesses](weaknesses.md).
- The guest shares the host's interpreter and libraries, and has one vCPU and 512 MiB of memory.
- `UDP` follows the same `iptables` rules as the other providers; a rule for a host name is a rule for the addresses
  it resolved to at load time.
- IPv4 only.
- Resource limits and seccomp are not configurable.
- Not tested in Docker, Podman or Kubernetes.
