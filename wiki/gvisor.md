# gVisor (gvisor)

## Solution in brief

[gVisor](https://gvisor.dev) runs the sandboxed process on a user-space kernel (the Sentry): the guest never makes a system call to the host kernel, it makes it to the Sentry, which re-implements Linux and reaches the host through a small, filtered set of calls. `os-sandbox=gvisor` starts `runsc` rootless, from an OCI bundle built from the rules, inside a private network namespace filtered by `iptables`.

## Advantages

- Compiled code and direct system calls hit the Sentry, not the host kernel: a kernel exploit has to cross two layers.
- Starts in about a second, with no VM disk or boot, unlike `qemu`.
- Nothing is exposed that a rule does not name: the root is an empty read-only directory, and each `expose-ro` / `expose-rw` rule is a bind mount.
- No capability, `noNewPrivileges`, host Unix sockets refused (`--host-uds=none`).
- Works in Docker and Podman without `--privileged` (see below).

## Disadvantages

- System-call heavy code is slower (6 to 8x on a loop of `os.stat`).
- A device rule (`expose-ro=/dev/...`) cannot be honoured: the guest has its own `/dev`. The provider logs a warning and the rule is not enforced.
- The guest `/proc` shows `/proc/gvisor` and `sentry-meminfo`: information, not a boundary.
- Needs `runsc` **and its sidecar directory** (`/usr/bin/gvisor-bin/`): the binary alone fails at the first guest.
- Linux and WSL only.

## How it works

1. The parent starts `unshare --user --map-root-user --net`: a private user and network namespace. The launcher script inside it waits.
2. The parent starts `slirp4netns` on that namespace, then forwards a host port to the guest daemon.
3. The launcher loads the `iptables` filter built from the `net=` rules (default drop, only the resolver of `slirp4netns` allowed for DNS), then starts `runsc run` with `--network=host`: the guest uses the filtered namespace of its launcher.
4. If the loopback, the filter or the config relay fails, the launcher exits and the guest never starts: the provider fails closed.

The OCI spec is written under the run directory: read-only root, `/tmp` as a tmpfs, `/proc`, one bind per exposed path (read-only wins when a path is exposed both ways), and a mask over each path an `ignore=` rule hides. The environment of the guest is exactly the one the rules allow.

## Rules

| Rule | Enforced by the OS | How |
|------|:---:|-----|
| `expose-ro` / `expose-rw` | ✅ | bind mounts of a read-only root |
| default deny of paths | ✅ | what is not mounted does not exist |
| `ignore=` | ✅ | an empty file or an empty tmpfs mounted over the path (reads succeed and return nothing) |
| `net=` | ✅ | `iptables` in the private namespace; UDP, TCP, host and port |
| env rules | ✅ | the OCI `process.env` is the whole environment |
| `import`, `eval-*` | ❌ | Python layer only |
| `python-api=` | ❌ | Python layer only: with `py-sandbox=false`, `os.system` runs |
| `/dev/...` exposure | ❌ | the guest has its own `/dev`; a warning is logged |

## Prerequisites

`runsc` with its sidecar directory `gvisor-bin` next to it (the `runsc` package of the [gVisor apt repository](https://gvisor.dev/docs/user_guide/install/)), `unshare`, `slirp4netns`, `iptables-restore`, `ip`, and read-write access to `/dev/net/tun`.

`unavailable_reason()` checks them in this order and reports the first that fails, with its remedy: a missing tool, the `gvisor-bin` directory (looked for next to the real `runsc`, links followed), `/dev/net/tun` (in a container: `--device /dev/net/tun`), an empty filter that `iptables-restore --test` cannot load, then a real guest (`runsc do /bin/true`). A host that forbids user namespaces, for example `kernel.apparmor_restrict_unprivileged_userns=1`, fails at the guest. Nothing is silently weakened. `gvisor.platform=kvm` also needs read-write `/dev/kvm`; it is refused at launch when missing, as the probe runs on the default platform only.

## Configuration parameters

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `gvisor.platform` | `systrap` | How `runsc` intercepts the guest's system calls: `systrap`, `ptrace` or `kvm`. Any other value is refused. |

The guest never calls the host kernel: the Sentry, gVisor's kernel written in Go and run in user space, answers each system call. The platform is only the way the call is caught, so the files, network and environment rules are the same on the three, and none of them boots a Linux kernel (`qemu` does).

| Platform | Mechanism | Needs | 50 000 `os.stat` | Start-up, cold / warm |
|----------|-----------|-------|:---:|:---:|
| `systrap` | seccomp filter: a system call raises a signal the Sentry handles | nothing special, works in a container or a VM | 0.17 s | +0.42s / +0.38s |
| `ptrace` | the Sentry stops the guest's threads at each call with `ptrace`, one context switch per call | `ptrace` allowed; the most widely supported | 0.42 s | +0.46s / +0.42s |
| `kvm` | the Sentry runs as the kernel of a KVM virtual machine, the guest as its user space | read-write `/dev/kvm`; slow in nested virtualization | 0.36 s | +0.43s / +0.39s |

`kvm` is not a Linux VM with a kernel of its own: it is still the Sentry, it makes the same host system calls, and it adds the host's KVM code to what the guest can reach. It pays off on bare metal for programs that make many system calls. Start-up is the extra time over `os-sandbox=none` (median of 7 runs, `py-sandbox=false`, see [what each costs](os-providers.md#what-each-costs)); the `os.stat` column comes from an earlier single run. An order of magnitude, not a benchmark. `unavailable_reason()` runs a guest on the default platform only: a missing `/dev/kvm` shows when the guest starts, not before.

## Using with Docker

The image is `python-sb-gvisor` (`make build-image-gvisor`, from `Dockerfile-gvisor`). The default Docker profile blocks what `runsc` needs. Either run `--privileged`, or lower only what stops it:

```bash
docker run --rm --device /dev/net/tun --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --cap-add NET_ADMIN python-sb-gvisor python-sb ...
```

## Using with Podman

Rootless Podman needs only the tun device:

```bash
podman run --rm --cap-add NET_ADMIN --device /dev/net/tun python-sb-gvisor python-sb ...
```

## Using with Kubernetes

The pod needs the `SYS_ADMIN` and `NET_ADMIN` capabilities, with the seccomp and AppArmor profiles `Unconfined`, as for `unshare`.

## Limits

- Stdin: `runsc` copies the host flags of the file descriptor into the guest. The launcher makes stdin blocking before it starts the guest, so a stdio program (an MCP server) reads it normally.
- Only the host mode is provided: the guest uses the filtered kernel network of its namespace. The user-space network stack of gVisor (`netstack`) is not offered, as `iptables` rules do not apply to it.
- `slirp4netns` exposes the host loopback to the guest at `10.0.2.2`, as it does for `unshare` and `bwrap`; a `net=` rule is the only thing that lets the guest reach it.

## References

- [gVisor](https://gvisor.dev)
- [OCI runtime spec](https://github.com/opencontainers/runtime-spec)
- [OS providers](os-providers.md)
