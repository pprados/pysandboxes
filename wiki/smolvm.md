# smolvm provider (`os-sandbox=smolvm`)

The sandboxed code runs in a micro-VM started by [smolvm](https://github.com/smol-machines/smolvm): libkrun as the
VMM, its own guest kernel, an OCI image as the root. The VM boundary is the isolation; nothing of the host is visible
unless a rule mounts it.

## How it works

`python-sb` and the daemon start `smolvm machine run --image <guest image> ... -- python -m pysandboxes.remote.main_sandbox`.

- **Guest image**: Python 3.12 and the dependencies of pysandboxes (`Dockerfile-smolvm-guest`). The package itself is
  mounted read-only at its host path, so what runs is the code of the host.
- **Config**: the host writes it to a file of a private directory mounted read-only at `/pysb`, which holds nothing
  else. The guest cannot open the host FIFO the other providers use.
- **Channel**: the guest listens on `/tmp/pysb.sock`; `--expose-socket` makes it reachable on a private Unix socket of
  the host. The guest needs no network for it. `remote-endpoint=tcp` is refused.
- **Environment**: the guest runs under `env -i` with the variables the rules grant: neither the host nor the image
  environment reaches it.
- **Capabilities**: `--unprivileged` by default, which drops most capabilities of the guest root.

## Prerequisites

- `smolvm` on the `PATH` (release archive, Linux x86_64 or aarch64, macOS arm64, Windows x86_64).
- `/dev/kvm` readable and writable on Linux.
- A guest image: `make build/smolvm-guest.tar` (needs Docker), then `PYSANDBOXES_SMOLVM_IMAGE=build/smolvm-guest.tar`
  or `smolvm.image=<path or registry reference>` in the profile.

`unavailable_reason()` checks the binary and `/dev/kvm`. A guest image that is missing fails the start with the
message that names both settings.

## Profile keys

| Key | Default | Effect |
|---|---|---|
| `smolvm.image` | `PYSANDBOXES_SMOLVM_IMAGE` | Guest image: a `docker save` archive or a registry reference |
| `smolvm.python` | `/usr/local/bin/python` | Python of the image |
| `smolvm.cpus`, `smolvm.mem` | smolvm's (4 vCPUs, 8 GiB) | `--cpus`, `--mem` (MiB) |
| `smolvm.unprivileged` | `true` | `false` keeps the full capabilities of the guest root |

Any other `smolvm.<key>` is refused. smolvm has **no seccomp and no Landlock switch** (the guest reports
`Seccomp: 0`): the guest is hardened by the VM and by dropping capabilities. `--user` is not offered, because a guest
user cannot write to the host directories mounted read-write.

## Rules

| Rule | Enforced by the OS | How |
|---|---|---|
| `expose-ro=` / `expose-rw=` | ✅ for directories | one `-v` per directory (virtiofs); a file is reported and stays hidden |
| `ignore=` | ❌ | a directory is mounted whole; only the Python layer hides the path. A warning is logged |
| `net=` TCP | ✅ by address, ❌ by port | `--allow-cidr`; a port opens every port of its address, and a port on any address stays closed |
| `net=` UDP | ✅ with the port | `--allow-udp CIDR:PORT` |
| `net=` IPv6 | ❌ | reported, stays closed |
| no `net=` rule | ✅ | no network at all |
| env | ✅ | `env -i` |

Measured on smolvm 1.33.0: a host outside the allow list is refused by IP and by name, raw-IP connections included;
UDP other than DNS is dropped once an allow list exists; DNS is answered by the host resolver and filtered by name.
Limits to know: a subdomain of an allowed host resolves, so DNS stays an exfiltration channel to those domains.

Mounts are limited by libkrun: about 8 virtiofs devices without a network, fewer with one. The package, the config and
the working directory take part of that budget, so a profile with many `expose` rules fails to start. The host Python
installation is never mounted: the guest has its own.

## Limits

- `smolvm` and its VMM run with the rights of the invoking user and are part of the trusted base.
- Any host process that can open the channel socket reaches the guest service; it sits in a private `0700` directory.
- Releases are checksummed, not signed: `Dockerfile-smolvm` pins the version and its SHA-256.
- Linux only for now. macOS and Windows tags wait for a `cross-os.yml` run.

## Running it

```bash
make build/smolvm-guest.tar
PYSANDBOXES_SMOLVM_IMAGE=build/smolvm-guest.tar python-sb --pysandboxes-config=my.profile -c 'print(1)'
```

In Docker or Podman: `make build-image-smolvm`, then `docker run --device /dev/kvm python-sb-smolvm`. This run is not
measured yet.

Tests: `pytest tests/integration_tests/remote/test_smolvm.py` and the `smolvm` row of
`test_usage_with_providers.py` and `test_guards_with_providers.py`.
