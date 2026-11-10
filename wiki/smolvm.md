# smolvm provider (`os-sandbox=smolvm`)

The sandboxed code runs in a micro-VM started by [smolvm](https://github.com/smol-machines/smolvm): its own guest kernel, an OCI image as the root. The VM boundary is the isolation; nothing of the host is visible
unless a rule exposes it.

## How it works

`python-sb` and the daemon start `smolvm machine run --image <guest image> ... -- /bin/sh -c <init script>`.

- **Guest image**: `python:<version>-slim` and the dependencies of pysandboxes (`Dockerfile-smolvm-guest`), where
  `<version>` is the Python of the host (`PYTHON_VERSION`): the guard code runs on the interpreter that wrote the
  config. The init script checks it first and stops with exit 72 on another version, naming the version to build. The
  package itself is shared read-only from the host, so what runs is the code of the host.
- **Files**: the VMM gives a micro-VM only a handful of virtio-fs devices, so there is not one mount per rule. The
  guest receives one read-only share per top directory of the paths the rules expose, and an init script that binds
  each path where the rule puts it, masks what `ignore=` names, then detaches every share: only the binds remain, and
  a share still mounted stops the guest. A writable directory keeps a share of its own.
- **Privileges**: the command runs as the user of the host, with an empty capability set and `no_new_privs`
  (`setpriv`): it cannot mount, remount or reach a share.
- **Config and standard input**: both travel on the standard input of the guest, see
  [the section below](#why-the-config-and-the-standard-input-share-one-stream).
- **Channel**: the guest listens on `/tmp/pysb.sock`; `--expose-socket` makes it reachable on a private Unix socket of
  the host. The guest needs no network for it. `remote-endpoint=tcp` is refused.
- **Environment**: the command runs under `env -i` with the variables the rules grant: neither the host nor the image
  environment reaches it.

## Why the config and the standard input share one stream

The guest must receive its config (rules, token) before anything of the user runs, and the other providers pass it
through a FIFO the child opens. A micro-VM has its own kernel, so every other way in is closed or unsafe:

- the host FIFO cannot be opened from the guest;
- a file would stay on the disk for anyone to alter, and a share would recreate that file;
- arguments and environment variables show in `ps` and `/proc` of the host, and the config holds the secret token;
- the channel socket exists only once the guest service runs, which needs the config first.

`smolvm machine run -i` relays its standard input to the guest: that is the one private, in-memory way in. The config
is therefore the head of that stream, read by `main_sandbox` with `--_config-on-stdin`. It is a pickle that ends where
it ends, so what follows stays unread, for the program.

What follows depends on how the sandbox is started:

| Started by | Standard input of the guest program |
|---|---|
| `python-sb` | the standard input of the caller, relayed after the config: `python-sb -`, `sys.stdin` and a pipe into the script work as in any other provider |
| a daemon (`sandboxes()`, `@sandbox`) | nothing: the application keeps its own standard input, as with the other providers |

The relay is a host process started by the launcher with `--_python-sb` only. It writes the config FIFO, then the
caller's input, into a private FIFO that is unlinked once opened, and dies with `smolvm` (`PR_SET_PDEATHSIG`), so the
launcher still replaces itself with `smolvm`. It reads the caller's input while the guest runs, even if the program
never reads it.

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
one per writable directory) is refused with a message that says so, rather than failing inside the VMM.

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
and the address filter all hold. The container suite (`make container-tests`) runs the four `smolvm` rows on each of Docker, Podman and Kubernetes,
privileged or not, and none of them needs a privilege:

| Engine | What the container gets |
|---|---|
| Docker | `--device /dev/kvm --group-add <gid of /dev/kvm> --user <uid>:<gid>` |
| Podman, rootless | the same, plus `--userns=keep-id`: otherwise the groups of the host are mapped to `nobody` and `/dev/kvm` stays unusable, even with `--privileged` |
| Kubernetes | a pod with no `securityContext` that asks a device plugin for the device (`resources.limits`); a privileged pod mounts `/dev/kvm` instead |

Two traps found by the suite. In a pod, `pip` run as root leaves a root-owned `/tmp/.cache` under the `HOME` of the image,
where smolvm keeps its state: the sandbox user needs a `HOME` of its own. And the 9p mount of minikube cannot be shared
with a guest, as its server fails on the directory reads of virtio-fs: the pod tests copy what they need to the
filesystem of the pod first.

Tests: `pytest tests/integration_tests/remote/test_smolvm.py`, the `smolvm` cases of `test_os_netfilter.py` (the guest
reaches the host on its address, never on loopback) and the `smolvm` row of
`test_usage_with_providers.py` and `test_guards_with_providers.py`.
