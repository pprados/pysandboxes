# Firejail

**Firejail** is an **OS-sandbox** provider that runs code in an isolated environment with restricted filesystem access, its own network namespace (on a bridge with socket rules, loopback only without), and configurable seccomp. It allows limiting disk access, network access, and system calls. See the [Firejail documentation](https://man7.org/linux/man-pages/man1/firejail.1.html) for details.

## Solution in brief

The host launches a Firejail sandbox with a generated profile: whitelist/read-only paths from **`expose-ro` / `expose-rw`** file rules, `--net=<bridge>` and netfilter rules (FIFO) for socket rules, `--net=none` (loopback only) without them. The sandbox runs `main_sandbox` which reads the configuration from a named pipe and starts the SSE server. The host talks to the sandbox via SSE on a local URL. With socket rules, the jail gets its own network namespace on a bridge (e.g. `docker0`, `br0`) and is reached at the address that bridge assigns. Only under an explicit `restricted-network yes` is no `--net` passed: the jail then shares the host network stack and the daemon listens on the host loopback (`127.0.0.1`).

## Advantages

| Aspect | Detail |
|--------|--------|
| **Isolation** | Filesystem whitelist, private network namespace (loopback only without socket rules), netfilter-based socket rules. |
| **Ease of use** | Single binary, profile from template + Py-sandboxes rules; no VM or kernel feature beyond namespaces. |
| **Security hardening** | Optional seccomp (allow/block lists) to restrict system calls. |
| **Alignment with other providers** | Same API (SSE, `call_in_sandbox`) and config flow (named pipe) as bwrap/unshare. |

## Disadvantages

| Aspect | Detail |
|--------|--------|
| **Docker / Podman** | Not usable in Docker, Podman or Kubernetes: inside a container, firejail runs the program without any isolation (see [Using with Docker](#using-with-docker)). |
| **Network** | With socket rules, `restricted-network no` must be set in `/etc/firejail/firejail.config` and a bridge must exist (e.g. `add-bridge.sh`); see [Prerequisites](#prerequisites) for the other two settings. The daemon mode always has a socket rule (its SSE port). Under an explicit `restricted-network yes`, the sandbox keeps the **host network** with a warning and only the Python layer enforces the socket rules. |
| **`/etc`** | `/etc` inside the jail is the `--private-etc` copy of the template (`hosts`, `resolv.conf`, `nsswitch.conf`, `ssl`, `pki`, `ca-certificates`). An `expose-*` rule under `/etc/` gets no `--whitelist` (it would put a tmpfs over `/etc` and break `--dns`), so a file outside that list stays invisible. |
| **Debug** | Profile and netfilter generation can be complex; check logs and Firejail options for troubleshooting. |

## How it works

1. **Host**: The daemon builds Firejail arguments from the template, file rules (whitelist/read-only/read-write), and optional socket rules. If socket rules are used, it generates netfilter rules and passes them via FIFOs (`--netfilter`, `--netfilter6`); without them, it adds `--net=none` unless `firejail.net` is set. Config is written to a named pipe; the sandbox reads it on startup.
2. **Launch**: The host runs `firejail [options] -- /usr/bin/env -i ... python -m pysandboxes.remote.main_sandbox --_named-pipe <path>`. Options include `--whitelist`, `--read-only`, `--net=<bridge>`, `--dns`, `--netfilter` when network rules are enabled, `--net=none` otherwise. `--x11=none` is added only with `--net` (a bridge or `none`): firejail refuses it while the abstract X11 socket is reachable, i.e. without a network namespace. Without one (explicit `restricted-network yes`), the template still blacklists `/tmp/.X11-unix` and empties `DISPLAY` and `XAUTHORITY`.
3. **Inside the sandbox**: `main_sandbox` loads the config from the pipe, applies Python guards, starts the SSE server on the expected port and waits for requests.
4. **Communication**: The host sends calls over SSE to the sandbox, on the bridge-assigned IP given by `--net`.

For more details, see the [Firejail documentation](https://firejail.wordpress.com/).

## Using with Docker

Firejail is **not** compatible with Docker. Inside a container, it concludes it already runs in a sandbox, prints `Warning: an existing sandbox was detected. <program> will run without
any additional sandboxing features` and starts the program unconfined. Neither `--privileged` nor `--force` changes
this: with firejail 0.9.74 in `docker run --privileged`, the program keeps the container's mount and PID namespaces.
The process starts and simple checks pass, but no kernel boundary applies. The project uses **one image per OS provider** (see [unshare](unshare.md), [bwrap](bwrap.md), [qemu](qemu.md)); there is **no container image for firejail**. Use **unshare**, **bwrap**, or **qemu** for container-based workflows.

## Using with Podman

Firejail is **not** compatible with Podman, for the same reason as [Docker](#using-with-docker). Use **unshare**, **bwrap**, or **qemu** with their respective provider images for container-based workflows.

## Using with Kubernetes

Firejail is **not** supported in Kubernetes (no `python-sb-firejail` image), for the same reason as
[Docker](#using-with-docker). Use **unshare** (`python-sb-unshare`), **bwrap** (`python-sb-bwrap`), or **qemu** (`python-sb-qemu`) and their documentation for Kubernetes.

## Configuration parameters

You can add Firejail-specific options in `.py-sandboxes`. Only four keys are recognized: `firejail.net`, `firejail.seccomp`, `firejail.seccomp.keep` and `firejail.seccomp.block`, each passed to Firejail as `--<option>=<value>` when the sandbox is started. Any other `firejail.<option>` line is not passed to Firejail.

### Network (firejail.net)

To use a specific bridge interface (e.g. for host communication), set:

- `firejail.net=my_bridge` — use the given bridge for the sandbox network.

If `firejail.net` is not set and socket rules are used, the daemon picks a default (e.g. `docker0` or the first available bridge).

### Seccomp (firejail.seccomp, firejail.seccomp.keep, firejail.seccomp.block)

To restrict system calls, use an allow-list or block-list:

- `firejail.seccomp=<path>` — path to a seccomp list file.
- `firejail.seccomp.keep=<syscalls>` — comma-separated list of allowed syscalls.
- `firejail.seccomp.block=<syscalls>` — comma-separated list of blocked syscalls.

To discover which syscalls your application uses, you can run:

```bash
scripts/extract_strace.sh <command to start your application>
```

Then add the resulting syscalls to `firejail.seccomp.keep=` (or `seccomp.block=`), separated by commas and without spaces.

## Prerequisites

- Firejail installed (e.g. `sudo apt install firejail`).
- For network and socket rules: a bridge (e.g. `docker0`, `br0`). Check with `ip link show type bridge`. The script `scripts/add-bridge.sh` can create one if needed.
- For socket rules (and so for the daemon mode), the `restricted-network` line of `/etc/firejail/firejail.config` decides:
  - `restricted-network no`: network filtering is applied (`--net`, `--dns`, `--netfilter`, `--netfilter6`).
  - no such line: the daemon logs an error and exits.
  - `restricted-network yes` (the stock value, e.g. on GitHub runners): the daemon warns and starts **without** the network setup, on the **host network**: the socket rules are not enforced by firejail, only by the Python guard, so native code, `ctypes` or a subprocess can reach any address.
- Without socket rules, `--net=none` is used whatever the `restricted-network` line says: firejail allows it to regular users.

## Recommendations

- Set `restricted-network no` in `/etc/firejail/firejail.config` and create a bridge before relying on socket rules. Under `restricted-network yes`, only the Python guard enforces them, and native code, `ctypes` or a subprocess can reach any address.
- Do not use Firejail in Docker, Podman or Kubernetes. Use [unshare](unshare.md), [bwrap](bwrap.md) or [qemu](qemu.md) with their provider images instead.
- Restrict system calls with `firejail.seccomp.keep=`, built from the output of the strace script shown above.
- Note that a file under `/etc` is visible only if it belongs to the `--private-etc` copy of the template.

## References

- [Firejail documentation](https://man7.org/linux/man-pages/man1/firejail.1.html)
- [Firejail documentation](https://firejail.wordpress.com/)
- [unshare provider](unshare.md), [bwrap provider](bwrap.md), [qemu provider](qemu.md)
