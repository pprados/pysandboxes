# Firejail

**Firejail** is an **OS-sandbox** provider that runs code in an isolated environment with restricted filesystem access, optional network namespace (bridge), and configurable seccomp. It allows limiting disk access, network access, and system calls. See the [Firejail documentation](https://man7.org/linux/man-pages/man1/firejail.1.html) for details.

## Solution in brief

The host launches a Firejail sandbox with a generated profile: whitelist/read-only bindings from file rules, optional `--net=<bridge>` for network, and netfilter rules (FIFO) for socket rules. The sandbox runs `main_sandbox` which reads the configuration from a named pipe and starts the SSE server. The host talks to the sandbox via SSE on a local URL. For security, code running in Firejail cannot reach host servers unless a network bridge is used (e.g. `docker0`, `br0`).

## Advantages

| Aspect | Detail |
|--------|--------|
| **Isolation** | Filesystem whitelist, optional private network namespace, netfilter-based socket rules. |
| **Ease of use** | Single binary, profile from template + Py-sandboxes rules; no VM or kernel feature beyond namespaces. |
| **Security hardening** | Optional seccomp (allow/block lists) to restrict system calls. |
| **Alignment with other providers** | Same API (SSE, `call_in_sandbox`) and config flow (named pipe) as bwrap/unshare. |

## Disadvantages

| Aspect | Detail |
|--------|--------|
| **Docker / Podman** | Not compatible with Docker and Podman (no Firejail in typical container images; bridge model differs). |
| **Network** | With socket rules, `restricted-network no` must be set in `/etc/firejail/firejail.config`; host access requires a bridge (e.g. `add-bridge.sh`). |
| **Debug** | Profile and netfilter generation can be complex; check logs and Firejail options for troubleshooting. |

## How it works

1. **Host**: The daemon builds Firejail arguments from the template, file rules (whitelist/read-only/read-write), and optional socket rules. If socket rules are used, it generates netfilter rules and passes them via FIFOs (`--netfilter`, `--netfilter6`). Config is written to a named pipe; the sandbox reads it on startup.
2. **Launch**: The host runs `firejail [options] -- /usr/bin/env -i ... python -m pysandboxes.remote.main_sandbox --_named-pipe <path>`. Options include `--whitelist`, `--read-only`, `--net=<bridge>`, `--dns`, `--netfilter` when network rules are enabled.
3. **Inside the sandbox**: `main_sandbox` loads the config from the pipe, applies Python guards, starts the SSE server on the expected port and waits for requests.
4. **Communication**: The host sends calls over SSE to the sandbox (localhost or bridge-assigned IP when using `--net`).

For more details, see the [Firejail documentation](https://firejail.wordpress.com/).

## Using with Docker

Firejail is **not** compatible with Docker. The project uses **one image per OS provider** (see [unshare](unshare.md), [bwrap](bwrap.md), [qemu](qemu.md)); there is **no container image for firejail**. Use **unshare**, **bwrap**, or **qemu** for container-based workflows.

## Using with Podman

Firejail is **not** compatible with Podman. Use **unshare**, **bwrap**, or **qemu** with their respective provider images for container-based workflows.

## Using with Kubernetes

Firejail is **not** supported in Kubernetes (no `python-sb-firejail` image). Use **unshare** (`python-sb-unshare`), **bwrap** (`python-sb-bwrap`), or **qemu** (`python-sb-qemu`) and their documentation for Kubernetes.

## Configuration parameters

You can add Firejail-specific options in `.py-sandboxes`. Any line of the form `firejail.<option>=<value>` is passed to Firejail as `--<option>=<value>` when the sandbox is started.

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
uv run extract_strace.sh <command to start your application>
```

Then add the resulting syscalls to `firejail.seccomp.keep=` (or `seccomp.block=`), separated by commas and without spaces.

## Prerequisites

- Firejail installed (e.g. `sudo apt install firejail`).
- For network and socket rules: a bridge (e.g. `docker0`, `br0`). Check with `ip link show type bridge`. The script `scripts/add-bridge.sh` can create one if needed.
- For socket rules: set `restricted-network no` in `/etc/firejail/firejail.config` so that network filtering can be applied.
