# Bubblewrap (bwrap)

**Bubblewrap (bwrap)** is an **OS-sandbox** provider that runs code in Linux namespaces with bind mounts and optional user namespace. The sandbox always gets its own network namespace (**`--unshare-net`**): **without socket rules** it only has loopback (default-deny). **With socket rules**, the daemon also starts **slirp4netns** on the host, and applies **iptables** inside the namespace so outbound traffic is filtered—similar in spirit to the unshare provider, but still under a single `bwrap` process tree. See the [bwrap documentation](https://man.archlinux.org/man/extra/bubblewrap/bwrap.1.en) for details.

## Solution in brief

The host runs `bwrap` with options from a template (e.g. `--clearenv`) plus **`--unshare-net`**, or **`--share-net`** when a `bwrap.*` override asks for it. It translates **`expose-ro` / `expose-rw`** file rules into bubblewrap bind mounts, plus minimal system binds (`/usr`, `/etc`, `/run` when present, `/lib`/`/lib64`, Python venv and `sys.path`). The sandbox runs `python -m pysandboxes.remote.main_sandbox` with config from a named pipe. The host talks to the sandbox via SSE on `http://localhost:PORT` (slirp4netns maps host loopback to the guest when a separate netns is used).

## Advantages

| Aspect | Detail |
|--------|--------|
| **Isolation** | Namespace-based (e.g. user, IPC); filesystem restricted to explicit expose rules (implemented as bind mounts) and ignore rules. |
| **Network modes** | Isolated netns by default: loopback only without socket rules, user-land filtering when socket rules are present. Shared host network only on explicit opt-out (`bwrap.share-net=yes`). |
| **Lightweight** | Single child process from bubblewrap’s perspective; no VM; fast startup. |
| **Alignment with other providers** | Same API (SSE, `call_in_sandbox`) and config flow (named pipe) as firejail/unshare; slirp/port-forward logic is shared with unshare via `slirp4netns_common`. |

## Disadvantages

| Aspect | Detail |
|--------|--------|
| **Network** | With socket rules, you depend on **slirp4netns** and iptables inside the namespace; opting out with `bwrap.share-net=yes` gives the sandbox the whole host network. |
| **Containers** | In Docker/Podman, bridge networking may still block reachability to the sandbox SSE port; `network_mode: host` is often needed when using `--share-net`. |
| **Dependencies** | Requires the `bwrap` binary. If you use **socket rules** (isolated netns path), **`slirp4netns`** must also be installed. |

## How it works

1. **Host**: The daemon loads the bwrap template from `pysandboxes/templates/bwrap.template`, applies env vars, then builds the command: template options + `--setenv` from rules, then **network**:
   - **`--share-net`** only if you force it with `bwrap.share-net=yes`, or if isolation is disabled with `bwrap.unshare-net=no` (or `0` / `false`).
   - **`--unshare-net`** otherwise (see [Configuration parameters](#configuration-parameters)): loopback only without socket rules, slirp4netns + iptables with them.
2. **Optional `bwrap.*` overrides**: Other `bwrap.<option>=<value>` lines become `--<option>=<value>` (or flag-only if value is empty). **`share-net` and `unshare-net` are handled by the logic above** and are not passed through as duplicate flags.
3. **Mounts**: Read-only bubblewrap binds for `/usr`, `/etc`, `/run` (when the directory exists, e.g. for `resolv.conf` under `/run`), `/lib`/`/lib64`, the resolved Python executable chain, `sys.path` and site-packages; then **`expose-ro` before `expose-rw`** from file rules, temp dir for the config pipe, and placeholder mounts for ignore rules (same idea as unshare).
4. **Launch**: The host runs `bwrap [args] -- python -m pysandboxes.remote.main_sandbox --_named-pipe <path>`. The config is written to the named pipe; the child reads it on startup.
5. **When `--unshare-net` is used**: After the bwrap child PID is known, a **background thread on the host** runs **slirp4netns** against that PID (shared helpers in `pysandboxes/remote/slirp4netns_common.py`). The child waits until the tap interface is ready, then **iptables** rules derived from socket rules are applied (DNS is expected at the usual slirp address **10.0.2.3**; inbound SSE from the host gateway **10.0.2.2** is allowed). **TCP/UDP ports** from inbound ALLOW rules (plus the SSE port) can be forwarded from host `127.0.0.1` into the namespace via the slirp API.
6. **Inside the sandbox**: `main_sandbox` loads the config, applies Python guards, starts the SSE server on the expected port and waits for requests.
7. **Communication**: The host uses **`http://localhost:PORT`**; with slirp, connections to host loopback are forwarded to the guest.

For more details, see the [bubblewrap documentation](https://github.com/containers/bubblewrap).

## Using with Docker

The bwrap provider can run inside Docker. The project uses **one image per OS provider**: the image for bwrap is `python-sb-bwrap` (tagged e.g. `:latest` or `:3.12`). Build it from the project root with:

```bash
make build-image-bwrap
```

Then run with the code mounted and the provider image. With **`--share-net`**, the sandbox uses the container’s network; ensure the host can reach the SSE port (e.g. publish the port or use `network_mode: host` where appropriate). If your profile uses **socket rules**, the image must include **`slirp4netns`** (and iptables as needed inside the namespace).

```bash
docker \
  run -it --rm \
  --privileged \
  -v "$(pwd)":/app \
  -w /app \
  python-sb-bwrap:latest \
  sh -c 'pip install -e . && OS_SANDBOX=bwrap python-sb -m tests.integration_tests.tst_usage'
```

## Using with Podman

Use the same provider image as for Docker:

```bash
make build-image-bwrap
```

```bash
podman \
  run -it --rm \
  --privileged \
  -v "$(pwd)":/app \
  -w /app \
  python-sb-bwrap:latest \
  sh -c 'pip install -e . && OS_SANDBOX=bwrap python-sb -m tests.integration_tests.tst_usage'
```

## Using with Kubernetes

Use the **provider image** `python-sb-bwrap:latest` (built with `make build-image-bwrap`). For minikube, build the images on the host and load them into the cluster: `make minikube-build-images` (runs `make build-images`, then `minikube image load` for each image). For this provider only: `make build-image-bwrap` then `minikube image load python-sb-bwrap:latest`.

Example Pod: same structure as for unshare (see [unshare.md](unshare.md#using-with-kubernetes)), with `image: python-sb-bwrap:latest` and the same volume mount for `/app`. Network and capabilities depend on whether you use socket rules (slirp + netns), no socket rule (netns with loopback only) or `bwrap.share-net=yes` (shared network); adjust `securityContext` (e.g. `privileged: true` or capabilities `SYS_ADMIN`, `NET_ADMIN`) as required by your cluster.

## Configuration parameters

You can add bwrap-specific options in `.py-sandboxes`. Any line of the form `bwrap.<option>=<value>` is interpreted as follows:

- **`bwrap.share-net=yes`** (or any non-empty value): use **`--share-net`**, with or without **socket rules**: the sandbox sees the host network. Socket-level OS filtering is then **not** applied; install slirp4netns is not required for that mode.
- **`bwrap.unshare-net=no`** (or `0` / `false`): disable the automatic **`--unshare-net`**; same effect as `bwrap.share-net=yes`.
- **Any other `bwrap.<option>`**: passed to bwrap as `--<option>=<value>` or `--<option>` if the value is empty.

If socket rules require the isolated network path and **`slirp4netns` is missing**, the daemon exits with an error suggesting installation or `bwrap.share-net=yes`.

## Prerequisites

- The **`bwrap`** binary (e.g. `sudo apt install bubblewrap`).
- **`slirp4netns`** when you use **socket rules** without `bwrap.share-net=yes` (e.g. `sudo apt install slirp4netns`).
