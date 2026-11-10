# smolvm provider (`os-sandbox=smolvm`)

The sandboxed code runs in a micro-VM started by [smolvm](https://github.com/smol-machines/smolvm): libkrun as the
VMM, its own guest kernel, an OCI image as the root. The VM boundary is the isolation; nothing of the host is visible
unless a rule exposes it.

## How it works

`python-sb` and the daemon start `smolvm machine run --image <guest image> ... -- /bin/sh -c <init script>`.

- **Guest image**: `python:<version>-slim` and the dependencies of pysandboxes (`Dockerfile-smolvm-guest`), where
  `<version>` is the Python of the host (`PYTHON_VERSION`): the guard code runs on the interpreter that wrote the
  config. The init script checks it first and stops with exit 72 on another version, naming the version to build. The
  package itself is shared read-only from the host, so what runs is the code of the host.
- **Files**: libkrun gives a micro-VM only a handful of virtio-fs devices, so there is not one mount per rule. The
  guest receives one read-only share per top directory of the paths the rules expose, and an init script that binds
  each path where the rule puts it, masks what `ignore=` names, then detaches every share: only the binds remain, and
  a share still mounted stops the guest. A writable directory keeps a share of its own. Same strategy as
  [libkrun](libkrun.md).
- **Privileges**: the command runs as the user of the host, with an empty capability set and `no_new_privs`
  (`setpriv`): it cannot mount, remount or reach a share.
- **Config**: it goes from the host FIFO to the standard input of the guest, read as `/dev/stdin`: it never touches
  the disk, so nothing can alter it.
- **Channel**: the guest listens on `/tmp/pysb.sock`; `--expose-socket` makes it reachable on a private Unix socket of
  the host. The guest needs no network for it. `remote-endpoint=tcp` is refused.
- **Environment**: the command runs under `env -i` with the variables the rules grant: neither the host nor the image
  environment reaches it.

## Prerequisites

- `smolvm` on the `PATH` (release archive, Linux x86_64 or aarch64, macOS arm64, Windows x86_64).
- `/dev/kvm` readable and writable on Linux.
- A guest image holding `setpriv` and `mount` (util-linux, in every Debian image): `make build-smolvm-guest`
  (needs Docker; writes `build/smolvm-guest-<python>.tar`, one archive per Python version), then `PYSANDBOXES_SMOLVM_IMAGE=build/smolvm-guest-3.13.tar` or `smolvm.image=<path or registry
  reference>` in the profile.

`unavailable_reason()` checks the binary and `/dev/kvm`. A guest image that is missing fails the start with the
message that names both settings.

## Profile keys

| Key | Default | Effect |
|---|---|---|
| `smolvm.image` | `PYSANDBOXES_SMOLVM_IMAGE` | Guest image: a `docker save` archive or a registry reference |
| `smolvm.python` | `/usr/local/bin/python` | Python of the image |
| `smolvm.cpus`, `smolvm.mem` | smolvm's (4 vCPUs, 8 GiB) | `--cpus`, `--mem` (MiB) |

Any other `smolvm.<key>` is refused. smolvm has **no seccomp and no Landlock switch** (the guest reports
`Seccomp: 0`): the guest is hardened by the VM and by the empty capability set of its command. `--unprivileged` is not
used, as the init script needs the capability to mount; the command has none when it starts.

## Rules

| Rule | Enforced by the OS | How |
|---|---|---|
| `expose-ro=` | ✅ | a read-only bind of the path, from a share of its top directory |
| `expose-rw=` | ✅ for directories | a share of its own, bound read-write |
| `ignore=` | ✅ | a file is masked with `/dev/null`, a directory with an empty `tmpfs`: a read returns nothing |
| `net=` TCP | ✅ by address, ❌ by port | `--allow-cidr`; a port opens every port of its address, and a port on any address stays closed |
| `net=` UDP | ✅ with the port | `--allow-udp CIDR:PORT` |
| `net=` IPv6 | ❌ | reported, stays closed |
| no `net=` rule | ✅ | no network at all |
| env | ✅ | `env -i` |

Measured on smolvm 1.33.0: a host outside the allow list is refused by IP and by name, raw-IP connections included;
UDP other than DNS is dropped once an allow list exists; DNS is answered by the host resolver and filtered by name.
Limits to know: a subdomain of an allowed host resolves, so DNS stays an exfiltration channel to those domains.

The host's own Python installation and the directories the image owns (`/usr`, `/etc`, `/lib`, ...) are never
exposed: the guest has its own. smolvm also refuses to share `/usr`, `/etc`, `/lib`, `/bin`, `/boot`, `/sys`, `/proc`,
`/dev`, `/run`, `/var` and `/var/log`, links resolved (`/opt`, `/home`, `/tmp` and `/var/lib` are accepted): a rule on
one of them is reported and not exposed.

The package of pysandboxes is shared from the host when it can be (a checkout, which then wins over the image's). An
installed package sits under `/usr`, which smolvm refuses to share: the guest then runs the copy in its image, which
`make build-smolvm-guest` installs from the same wheel. Rebuild the archive when pysandboxes changes. A profile that needs more than 6 shares (top directories of the read-only paths, plus
one per writable directory) is refused with a message that says so, rather than failing inside libkrun.

## Limits

- `smolvm` and its VMM run with the rights of the invoking user and are part of the trusted base.
- Any host process that can open the channel socket reaches the guest service; it sits in a private `0700` directory.
- The share of a top directory holds more than the rules name, until the init script detaches it: no sandboxed code
  runs before that.
- The guest runs as the user of the host: a file it must read has to be readable by that user, as the guest root has
  no capability to override it.
- Releases are checksummed, not signed: `Dockerfile-smolvm` pins the version and its SHA-256.
- Needs `/dev/kvm`: in a container, the device and a user in its group. Linux only for now. macOS and Windows tags wait for a `cross-os.yml` run.

## Running it

```bash
make build-smolvm-guest
PYSANDBOXES_SMOLVM_IMAGE=build/smolvm-guest-3.13.tar python-sb --pysandboxes-config=my.profile -c 'print(1)'
```

In Docker, with the image `python-sb-smolvm` (`make build-image-smolvm`: smolvm 1.33.0 pinned by SHA-256, and the guest
archive):

```bash
docker run --rm --device /dev/kvm --group-add $(stat -c %g /dev/kvm) --user $(id -u):$(id -g) \
    -v $PWD:/work python-sb-smolvm python-sb --pysandboxes-config=/work/my.profile -c 'print(1)'
```

The container must run as a user that can open `/dev/kvm`: smolvm lowers the privileges of a root caller and its VMM
then loses the device (`KvmOpen(Error(13))`, even with `--privileged`), so `--user` and `--group-add` are required. The
guest archive is world-readable and `HOME=/tmp` for the same reason: a container user has no other place to write.
Measured: guest kernel 6.18.60 against the host's 7.0, `expose-ro`, `expose-rw` (the write reaches the host), `ignore=`
and the address filter all hold. The container suite (`make container-tests`) runs the four `smolvm` rows under Docker as
the user of the caller with `/dev/kvm`; Podman and Kubernetes are not measured, and their rows are skipped.

Tests: `pytest tests/integration_tests/remote/test_smolvm.py` and the `smolvm` row of
`test_usage_with_providers.py` and `test_guards_with_providers.py`.
