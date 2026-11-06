# libkrun

The `libkrun` provider runs the sandbox in a KVM micro-VM. There is no disk image and no cloud-init: the guest kernel
boots in tens of milliseconds, builds a small root out of the host's, and starts the host's own interpreter. A whole
run takes about a second, against 20 to 40 seconds for [`qemu`](qemu.md).

```python
from pysandboxes.sandboxes_api import sandboxes

with sandboxes(os_sandbox="libkrun"):
    ...  # runs in the micro-VM
```

## Prerequisites

- Linux (or WSL) with read/write access to `/dev/kvm`.
- `libkrun.so` and `libkrunfw.so` installed on the host.
- `setpriv`, `pivot_root` and `mount` (util-linux), which the guest runs through the shared root.
- For a profile with an outgoing `net=` rule: `unshare`, `slirp4netns`, `iptables-restore`, `ip` and `passt`.

`unavailable_reason()` checks `/dev/kvm` and the two libraries and says which one is missing. The interpreter needs no
`AF_VSOCK` support: the guest creates its vsock socket through libc (`ctypes`).

## libkrun version

The provider uses the C API that libkrun generates with ffier (`krun_vmm_builder_*`, `krun_vsock_device_*`,
`krun_net_device_*`), which the releases up to 1.19 do not have. It is built on libkrun `2.0.0-dev`, the `main` branch of
[libkrun](https://github.com/libkrun/libkrun), with libkrunfw 5.5.0. **Follow the publication of libkrun v2 and move to
it**: the API of a development branch can change, and `Dockerfile-libkrun` pins a commit for that reason.

## How it works

- **Channel.** libkrun relays a Unix socket the host binds to a vsock port of the guest. A shim started by the guest,
  under the host's interpreter, listens on that vsock port and relays to the Unix socket of the sandbox daemon. The
  host waits for the shim's ready file before it connects: libkrun aborts when a host connection reaches a port nobody
  listens on. `remote-endpoint=tcp` or a fixed `port=` cannot work with this provider.
- **Files.** The kernel boots on the host root, shared read-only through virtio-fs. The guest's init script builds a
  new root in a tmpfs out of it and switches to it with `pivot_root`, then detaches the old one: the guest sees the
  system (`/usr`, `/etc`, `/bin`, `/sbin`, `/lib`, `/lib64`), the interpreter and its libraries, and what the rules
  name, nothing else. A path of `expose-ro=` is a read-only bind of the old root. A directory of `expose-rw=` is a
  virtio-fs share of its own, the only writable host path. A file an `ignore=` rule names is masked: a read returns
  nothing. The new root is read-only, `/tmp` is a private tmpfs, and `/dev` and `/proc` are the guest's own. A
  failure to build the root stops the micro-VM, so the command never runs on a root it was not meant to see.
- **Privileges.** The command runs as the user of the host, with no supplementary group, an empty capability set and
  `no_new_privs`: it cannot mount, remount or reach the old root. Only the init script, which sets the root up, runs
  as root, and it ends before the command starts.
- **Environment.** The command starts with `env -i`: it receives the variables the rules allow, plus `PYTHONHOME` and
  `PYTHONPATH`, which tell the interpreter where it is.
- **Network.** Without an outgoing `net=ALLOW` rule the guest has no network device: only its loopback exists, and the
  host sees no connection, whatever the guest does. With one, the guest gets a virtio NIC whose other end is `passt`,
  started in a private user and network namespace where the host loads an `iptables` filter built from the `net=`
  rules (the same translation as `unshare` and `gvisor`) and attaches `slirp4netns`. Every connection `passt` opens
  crosses that filter, so native code in the guest cannot walk around the Python guard. The micro-VM itself stays
  outside the namespace: libkrun does not boot inside a user namespace.
- **Exit code.** A micro-VM that ends without the guest reporting an exit code is a failure (70), never a success.

## Limitations

- The system directories and the interpreter's tree are readable, as in the other providers; a file elsewhere on the
  host is not, unless a rule names it. `/etc` is exposed whole: what the user may read there, the guest may read.
- The guest runs as the user of the host: when that is `root`, it is `root` without capability.
- The guest shares the host's interpreter and libraries, and has one vCPU and 512 MiB of memory.
- `UDP` follows the same `iptables` rules as the other providers; a rule for a host name is a rule for the addresses
  it resolved to at load time.
- IPv4 only.
- A rule on `/dev` or `/proc` is not honoured: the guest has its own.
- Resource limits and seccomp are not configurable.
- Not tested in Kubernetes. In Docker the micro-VM does not yet boot: the image builds and the tools and libraries are
  found, but the guest ends without an exit code, even with `--privileged`; the provider runs on the host. In Docker and Podman the container needs `--device /dev/kvm` (and `--device /dev/net/tun` for
  a profile with a `net=` rule); the image `python-sb-libkrun` (`make build-image-libkrun`) compiles libkrun and
  libkrunfw from source in a first stage and keeps only their libraries.
