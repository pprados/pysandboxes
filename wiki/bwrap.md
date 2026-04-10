# Bubblewrap (bwrap)

**Bubblewrap (bwrap)** is an **OS-sandbox** provider that runs code in Linux namespaces with bind mounts and optional user namespace. It allows limiting filesystem access and, in the current implementation, shares the host network so that socket rules and DNS work without a bridge. See the [bwrap documentation](https://man.archlinux.org/man/extra/bubblewrap/bwrap.1.en) for details.

## Solution in brief

The host runs `bwrap` with options from a template (e.g. `--clearenv`, `--share-net`) and adds bind mounts from file rules plus minimal system binds (`/usr`, `/etc`, `/lib`, Python venv and sys.path). The sandbox runs `python -m pysandboxes.remote.main_sandbox` with config from a named pipe. The host talks to the sandbox via SSE on `http://localhost:PORT`. There is no separate network namespace by default: `base_url` is localhost.

## Advantages

| Aspect | Detail |
|--------|--------|
| **Isolation** | Namespace-based (e.g. user, IPC); filesystem restricted to explicit bind mounts and file rules. |
| **Simplicity** | No bridge or netfilter; shared network keeps DNS and socket rules working with minimal setup. |
| **Lightweight** | Single process, no VM; fast startup. |
| **Alignment with other providers** | Same API (SSE, `call_in_sandbox`) and config flow (named pipe) as firejail/unshare. |

## Disadvantages

| Aspect | Detail |
|--------|--------|
| **Network** | Shares host network; no per-sandbox network stack. For full network isolation use unshare or QEMU. |
| **Containers** | In Docker/Podman, bridge networking may not provide a route for the sandbox; `network_mode: host` is often needed for bwrap. |
| **Dependencies** | Requires the `bwrap` binary (e.g. package `bubblewrap`). |

## How it works

1. **Host**: The daemon loads the bwrap template from `pysandboxes/templates/bwrap.template`, applies env vars, then builds the command: template options + `--setenv` from rules, `--share-net`, optional `bwrap.*` overrides, read-only binds for `/usr`, `/etc`, `/lib`/`/lib64`, Python executable and libraries, then file-rule binds (ro-bind / bind), temp dir for the config pipe, and overlay mounts for ignore rules.
2. **Launch**: The host runs `bwrap [args] -- python -m pysandboxes.remote.main_sandbox --_named-pipe <path>`. The config is written to the named pipe; the child reads it on startup.
3. **Inside the sandbox**: `main_sandbox` loads the config, applies Python guards, starts the SSE server on the expected port and waits for requests.
4. **Communication**: The host sends calls over SSE to `http://localhost:PORT`.

For more details, see the [bubblewrap documentation](https://github.com/containers/bubblewrap).

## Using with Docker / Podman

The bwrap provider can run inside Docker or Podman. Because it uses `--share-net`, the sandbox uses the container’s network; if the container uses bridge networking, ensure the host can reach the SSE port (e.g. publish the port or use `network_mode: host` where appropriate).

## Configuration parameters

You can add bwrap-specific options in `.py-sandboxes`. Any line of the form `bwrap.<option>=<value>` is passed to bwrap as `--<option>=<value>` (or `--<option>` if the value is empty). Examples:

- `bwrap.unshare-net` — create a separate network namespace (no value). When set, the sandbox has its own network; you must arrange connectivity to the SSE server (e.g. veth or port forwarding) if you use this option.

## Prerequisites

- The `bwrap` binary installed (e.g. `sudo apt install bubblewrap`).
