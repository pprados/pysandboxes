# OS-level sandbox providers

## OS-sandbox vs Py-sandbox

PySandboxes combines two isolation layers:

- a sandbox at the Python API level (**py-sandbox**)
- another sandbox at the OS level (**os-sandbox**)

The Python layer blocks restricted Python operations. It cannot block native extensions or direct kernel calls. Database drivers, for example, often use compiled code ([details](database.md)). The Python layer also does not make an untrusted dependency safe.

Add an OS provider to contain native code and direct system calls. OS providers enforce operating-system rules; they do not implement Python-specific controls such as the import whitelist.

## Which provider?

Start here; the matrix below gives the detail behind each line.

| Situation | Provider |
|---|---|
| Default on Linux: nothing to install, no privilege, files and TCP ports | [`landlock`](landlock.md) |
| Untrusted native code, or host and UDP filtering, with the lightest namespaces | [`bwrap`](bwrap.md) |
| Untrusted native code, or host and UDP filtering, with only user namespaces, `slirp4netns` and `iptables` | [`unshare`](unshare.md) |
| Strongest separation, in a VM (more than 20 s to start) | [`qemu`](qemu.md) |
| Smaller QEMU machine, x86_64 Linux, with at most eight virtio-mmio transports | [`qemu-microvm`](qemu-microvm.md) |
| Compiled code or kernel exploits, user-space kernel, starts in about a second | [`gvisor`](gvisor.md) |
| Compiled code or kernel exploits, with its own guest kernel in a micro-VM (KVM, about a second), TCP filtered by address only, no IPv6, Linux only | [`smolvm`](smolvm.md) |
| Resource limits and seccomp | [`firejail`](firejail.md) |
| Inside Docker, Podman or Kubernetes | [`landlock`](landlock.md), [`qemu`](qemu.md) or [`qemu-microvm`](qemu-microvm.md) unprivileged; [`unshare`](unshare.md) or [`bwrap`](bwrap.md) with `--privileged`; [`smolvm`](smolvm.md) unprivileged, as a user of the `kvm` group with `/dev/kvm` (Docker `--device`, `--group-add`, `--user`; Podman also `--userns=keep-id`; Kubernetes through a device plugin); [`gvisor`](gvisor.md) with `--privileged` or its lowered confinement (see below) |
| Files and ports on macOS (Seatbelt, no host filtering) | [`sandbox-exec`](sandbox-exec.md) |
| Files and network on Windows, without administrator rights (AppContainer token, no host or port filtering) | [`appcontainer`](appcontainer.md) |
| Process separation only, no OS boundary (also on macOS, and the fallback on Windows) | [`subprocess`](subprocess.md) |
| No sandbox at all: plain Python, for comparison or trusted code | `none` |

Two limits to know before choosing `landlock`: it denies a path but cannot hide it, and it does not protect the host's named Unix sockets (see [Host sockets under `/run`](#host-sockets-under-run)). Against untrusted native code, prefer `bwrap` or `unshare`.

## All providers

The providers that can wrap the Python sandbox are:

| Technology                                                      | Implementation<br/>&amp;<br/>Configuration | Specifics                                                                    | Description                                                                                                                              |
|-----------------------------------------------------------------|--------------------------------------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| [subprocess](subprocess.md)                                     | [here](subprocess.md)                 | • no complementary security                                                  | Separate Python process of the same user, with no OS boundary. Runs on every platform.                                                   |
| [bwrap](https://github.com/containers/bubblewrap)               | [here](bwrap.md)                      | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [firejail](https://github.com/netblue30/firejail)               | [here](firejail.md)                   | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html) | [here](unshare.md)                    | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels using `unshare`, `slirp4netns` and `iptables`. |
| [landlock](https://landlock.io/)                                | [here](landlock.md)                   | • Directory access<br/>• Network TCP port filtering                          | This is a technology that allows an auto isolation inside a Linux process.                                                               |
| [qemu](https://www.qemu.org/)                            | [here](qemu.md)                       | • Total emulation of OS and CPU                                              | No need of privilege. Use KVM if it's possible, else use the emulation.                                                                  |
| [qemu-microvm](https://www.qemu.org/docs/master/system/i386/microvm.html) | [here](qemu-microvm.md) | • Separate guest kernel<br/>• virtio-mmio only<br/>• Linux x86_64 | Direct kernel boot; KVM recommended. Eight transport limit; TCG is much slower. |
| [gvisor](https://gvisor.dev)                             | [here](gvisor.md)                     | • User-space kernel (Sentry)<br/>• Disk mapping<br/>• File filtering<br/>• Network filtering | `runsc` in a private network namespace filtered by `iptables`, with `slirp4netns`. |
| [smolvm](https://github.com/smol-machines/smolvm) | [here](smolvm.md) | • Micro-VM with its own kernel (KVM)<br/>• Disk mapping (directories)<br/>• Network filtering by address | `smolvm machine run` on an OCI image, the channel over a Unix socket; no namespace or `iptables` on the host. |
| sandbox-exec | [here](sandbox-exec.md) | • Seatbelt path and port filtering<br/>• Deprecated by Apple<br/>• No remote host/IP filtering | Legacy macOS-only profile launcher. |
| [appcontainer](appcontainer.md) | [here](appcontainer.md) | • File ACLs<br/>• AppContainer network capabilities<br/>• Job Object | Windows-only provider; its administrator and standard-user suites pass, and `cross-os.yml` runs them on the Windows runner. |

The `none` column means plain Python with no sandbox. `py-sandbox` shows the Python layer. Each OS column shows that provider's controls; it does not include Python controls. In practice, OS providers wrap the Python layer.

A ❌ means the provider does not enforce that control. The Python layer may still enforce it. For example, Landlock cannot filter imports, but blocks compiled code and direct syscalls. Combined controls provide the effective protection.

[`sandbox-exec`](sandbox-exec.md) is the macOS provider. Apple has deprecated the command, and it creates no namespace, so it is not a VM boundary. See [the provider page](sandbox-exec.md) before selecting it.

| Guard                    | none | py-sandbox | landlock  |  unshare  |   bwrap   | firejail |       qemu       | gvisor | smolvm | sandbox-exec | appcontainer¹ |
|--------------------------|:----:|:----------:|:---------:|:---------:|:---------:|:------:|:----------------:|:--------:| :--------: | :----------: |:-----------:|
| Isolation                |  ❌   |  Process   | Linux ABI | Namespace | Namespace | Namespace | VM+<br/>emulator | User-space<br/>kernel | MicroVM+<br/>own kernel | Seatbelt | AppContainer |
| Python code              |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ | ❌ |
| Compiled code            |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | ✅ |
| env                      |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | ✅ |
| import                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ | ❌ |
| expose-ro/rw=path        |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | ✅ |
| ignore=*                 |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | Partial² |
| python-api=*             |  ❌   | ✅ |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  | ❌ |  ❌  |  ❌  |
| eval-*                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ | ❌ |
| **Network**              |      |            |           |           |           |        |                  |  | |  |  |
| • TCP                    |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | Partial³ |
| • UDP                    |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | Partial³ |
| • host                   |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ❌ | ❌³ |
| • port                   |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | UDP only⁴ | ✅ | ❌³ |
| OS-sandbox               |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | ✅ |
| Vm compatible            |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ | ✅ |
| **Docker / Podman**      |      |            |           |           |           |        |                  |  | |  |  |
| • unprivileged           |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | ❌ | ✅⁵ | n/a | n/a |
| • --privileged           |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ✅         | ✅ | ✅⁵ | n/a | n/a |
| **Kubernetes**           |      |            |           |           |           |        |                  |  | |  |  |
| • unprivileged pod       |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | ❌ | ✅⁵ | n/a | n/a |
| • SYS_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | ✅ | not needed⁵ | n/a | n/a |
| • NET_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | ✅ | not needed⁵ | n/a | n/a |
| **Extra**                |      |            |           |           |           |        |                  |  | |  |  |
| • Resource limits        |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |     ✅  |        ✅         | ❌ | ✅ | ❌ | ❌ |
| • Seccomp                |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |   ✅    |        ✅         | ❌ | ❌ | ❌ | n/a |
| • Latency                | <1s  |    <1s     |    <1s    |    <1s    |    <1s    |    <1s |      >20s        | ~1s | ~1s | <1s | Pending |
| **OS**                   | Any  |    Any     |   Linux   |   Linux   |   Linux   |  Linux |      Linux       | Linux | Linux | macOS | Windows |

¹ `appcontainer` is Windows-only: the Docker and Kubernetes rows do not apply. ² `ignore=` covers only paths present at launch, and their names may remain listable. ³ AppContainer denies outbound network access by default. An `ALLOW` `net=` rule grants a broad public-Internet or private-network capability; AppContainer itself does not filter host, port, protocol, or loopback. The Python guard checks the first three only while enabled, so native code can bypass those checks. Loopback is blocked by AppContainer even when a rule allows it. ⁴ `smolvm` filters TCP by address, never by port: a TCP rule with a port opens every port of its address, and a port on any address stays closed. A UDP rule keeps its port. ⁵ `smolvm` needs no privilege and no capability, only `/dev/kvm` and a non-root user in its group, so the privileged rows add nothing and the `SYS_ADMIN` and `NET_ADMIN` rows are not needed. Docker: `--device /dev/kvm --group-add <gid> --user`. Rootless Podman: the same with `--userns=keep-id`, which is what leaves the device usable to the user. Kubernetes: a pod with no `securityContext` that asks a device plugin for the device (`resources.limits`), or a privileged pod that mounts `/dev/kvm`; the project's tests use [a plugin manifest](../tests/containers_tests/kube-kvm-device-plugin.yaml) for the first.

QEMU and QEMU microvm pass the `readonly=on` export option for `expose-ro` mounts; end-to-end native guest write regressions cover both. Microvm fails closed when the eight virtio-mmio transports are exhausted. Landlock denies TCP bind/connect by default on ABI v4+, but cannot filter UDP and is unavailable below ABI v4. See [QEMU security limitations](qemu.md#security-limitations), [QEMU microvm limits](qemu-microvm.md#limits), and [Landlock limits](landlock.md#limits).

### QEMU microvm rule enforcement

| Rule | OS-layer result | Evidence and limit |
|---|---|---|
| `expose-ro` | Read-only virtio-9p export | Native guest open-for-write is refused. |
| `expose-rw` | Writable virtio-9p export | Native guest create/write succeeds only in the exposed directory. |
| Unexposed files | Not exported | Native guest read fails; each distinct share consumes a transport. |
| `ignore=` | Guest bind-mount masks original content | Native guest sees no original bytes. |
| `net=` | Guest iptables filter | Native deny and allow controls pass, with a host control. |
| Environment | Host allowlist copied to guest | Unlisted host variables are absent. |
| Guest setup | Required mount failures stop startup | Fault injection verifies no user code starts. |

These OS checks ran with Python guards disabled where applicable. Python import, API and `eval-*` rules remain in the Python layer.

On `sandbox-exec`, the `• host` row is ❌ because Seatbelt filters by protocol and port only: `net=ALLOW|TCP|203.0.113.7|443|OUT` becomes "TCP port 443, any remote host". Only the Python socket guard still checks the host, so with `py-sandbox=false` native code reaches any host on an allowed port. A port rule is still enforced by the kernel. When DNS (UDP 53) is allowed, the rule becomes a grant on the system resolver socket (`mDNSResponder`), not a UDP rule. Details: [network limitations](sandbox-exec.md#network-limitations).

`ignore=` is enforced differently by each technology: **py-sandbox** and **firejail** make the path disappear (`FileNotFoundError`), **unshare** and **sandbox-exec** have the OS refuse it (`PermissionError`), and **bwrap**, **qemu**, **qemu-microvm** and **gvisor** mask it, so a read returns no original file contents. **landlock** denies access to a path but cannot hide one, so it has no equivalent: with `--py-sandbox=False` an ignored file stays readable there.

**landlock** under Kubernetes needs no capability at all, which is why its three Kubernetes rows are identical: unlike **unshare** and **bwrap**, it never asks the pod for `SYS_ADMIN` or `NET_ADMIN`, it restricts itself from the inside. Its single requirement sits elsewhere, on the *node*: the kernel must expose Landlock ABI v4 (Linux 6.7+) for the provider's default TCP deny policy, and the ABI seen inside the pod is the node's, not the image's. On a managed cluster, where the node kernel is not yours to choose, verify it before relying on it. Native UDP remains outside Landlock's network controls.

On the **Extra** rows, **bwrap** is `❌` twice, for two different reasons. It has no resource-limit option at all, and the `bwrap.<option>=` passthrough can only forward flags bubblewrap already understands. Seccomp it *does* expose, but only as `--seccomp FD` / `--add-seccomp-fd FD`, which expect a file descriptor carrying a compiled BPF program; a textual configuration line cannot provision one, so the feature is out of reach here rather than missing from the tool.

For **qemu**, the resource that is bounded is memory: `qemu.memory` caps guest RAM (2048 MiB by default). The vCPU count is not exposed, and unlike `bwrap.*`, unknown `qemu.*` keys are not forwarded to the command line, only the documented ones are read.

A `❌` in the **py-sandbox** column is a deliberate posture, not a gap: with `py-sandbox=False` (or `--py-sandbox=False`) the Python layer is switched off on purpose, so `python-api=`, `eval-*`, `import=`, the Python-code guard and, on **landlock**, `ignore=` stop being enforced. Only the OS layer of the chosen technology remains. Use it when the sandboxed code is trusted not to attack the interpreter itself and you want the OS boundary alone; keep the Python layer on otherwise.

The parent deserializes what the sandboxed child returns over the local SSE transport. Reconstructing a returned object can run arbitrary code in the parent, outside the sandbox, so that channel is filtered by a restricted unpickler. By default, `remote-result-mode=data-only` accepts values only: primitive data, built-in containers, paths, dates and time zones, decimals, fractions, UUIDs and IP addresses, from a closed list. `remote-result-mode=objects` rebuilds application objects behind a fail-open denylist of dangerous gadgets; turn that denylist off with `remote-result-guard=false` only if a legitimate return value is wrongly rejected. Learning mode recommends a result mode from the observed results and warns in the generated rules if application objects are needed.

On the exception channel the guard is fail-closed, and an exception's state routinely holds a type it refuses — `httpx.ConnectError` carries the `httpx.Request` it failed on. So the child also sends a descriptor of the exception (class, message, denials), and the parent falls back to it rather than losing the refusal. An exception that crosses that way keeps its class, its message, its traceback and `sandbox_denials(e)`, but arrives **without its attributes**: `except httpx.ConnectError as e` still works, `e.request` does not. See [here](transport-unpickle-guard.md).



> During the learning phase, `os-sandbox` is forced to `subprocess`.

> Note that a network constraint may not be detected during learning if the call is made by compiled code. The **OS-sandbox** configuration will not allow the connection. Simply add the missing rule *manually*. It will be added when the **os-sandbox** is launched.

To select the **OS-sandbox** provider, set the parameter `os-sandbox` in the config file. `OS_SANDBOX` only takes effect where that line reads it, as a generated profile does (`os-sandbox=${OS_SANDBOX:-landlock}`):

```shell
OS_SANDBOX=unshare python-sb -m my-module
```

A generated profile names its default in clear: `landlock` on Linux when the kernel supports it (no extra binary needed), otherwise `subprocess`, with a warning when Linux lacks Landlock. The choice is made once, when the file is written, and read as written afterwards; learning always runs under `subprocess` regardless (see above). `landlock` protects files and TCP ports but not the host's named Unix sockets (see [Host sockets under `/run`](#host-sockets-under-run)): against untrusted native code, write `os-sandbox=bwrap` or `os-sandbox=unshare`.

To pin a provider so the environment cannot downgrade it, write it literally, e.g. `os-sandbox=bwrap` — `learn=false` does not prevent this downgrade either (see [use-cases](use-cases.md#what-the-rule-file-does-not-show)). A named provider, `landlock` included, is never downgraded: if it is unavailable, the sandboxed process fails closed instead of silently dropping to `subprocess`.

> Need help: can you propose a PR to integrate some solution for Apple OS ?

### How the host reaches the sandbox: `remote-endpoint`

`remote-endpoint=auto` is the default: when the provider and the platform allow it, the host binds a Unix socket (mode 0600, private directory) and hands the listening descriptor down to the child, which then needs no file rule and no network rule for the channel and cannot replace the socket. Otherwise the channel stays on a local TCP port (`net=ALLOW|TCP|*|<port>|IN`, injected for the child). `auto` falls back to TCP for a provider that cannot hand a descriptor down, for a fixed `port=`, off Linux and macOS (Windows Python has no `AF_UNIX`), and where no Unix socket can be bound. `remote-endpoint=tcp` forces TCP; `remote-endpoint=unix` is an error where `auto` would fall back.

| Provider | Unix socket |
|---|---|
| subprocess | ✅ |
| landlock | ✅ |
| bwrap | ✅ |
| firejail | ✅ |
| unshare | ✅ |
| sandbox-exec | ✅ macOS: Seatbelt lets the sandbox accept on the inherited socket, with no network rule |
| appcontainer | ❌ Windows Python has no `socket.AF_UNIX`; the channel stays on TCP |
| qemu | ✅ QEMU creates the socket (`hostfwd=unix:`); the guest keeps serving TCP behind the forward |
| gvisor | ❌ the guest cannot accept on a handed-down socket, and `--host-uds=open` would let it reach host sockets |
| smolvm | ✅ the guest listens on a Unix socket that `--expose-socket` makes reachable on the host, and needs no network for it; `remote-endpoint=tcp` is an error |

Not supported by this layer: Windows named pipes (uvicorn cannot serve on them) and anonymous pipes (no accept loop).

### How host names of `net=` rules are resolved: `net-resolve`

`net-resolve=pinned|runtime` picks when the host name of a `net=` rule (`net=ALLOW|TCP|api.example.com|443|OUT`) becomes addresses. The default is not decided yet; without the key the value is `pinned`.

- `pinned` resolves the name once, at start, and freezes the addresses in the ruleset and in `/etc/hosts`. A name whose addresses rotate is refused once they change.
- `runtime` resolves the name when the sandboxed program asks. The sandbox DNS (`10.0.2.3`) is redirected to a filtering resolver on the host, which answers only the names a rule allows (`NXDOMAIN` otherwise), opens the addresses of an allowed answer in the sandbox firewall before it replies, and closes them when their TTL (clamped to 60 s to 1 h) is over. The firewall keeps the protocols and ports of the rule, a static `DENY` keeps precedence, and a resolver the program names itself (`8.8.8.8`, DoT, DoH to an unlearned address) meets the default `DROP`.

`runtime` is available for `unshare`, `bwrap`, `gvisor`, `qemu` and `firejail` (as root only), and needs `nsenter` and `iptables` on the host. Under `firejail` only root can enter the network namespace of a jail (`nsenter` fails with EPERM for a regular user), so the resolver joins it with `firejail --join-network`, and a regular user gets a configuration error. Under `qemu` the guest applies its own firewall, so the host talks to a small helper process of the guest through a second forwarded port; it needs no `nsenter`. Any other provider rejects it with a configuration error rather than falling back to `pinned`. A rule names a host as `name` (the name and its subdomains), `=name` (the name only) or `*.name` (subdomains only). Limits: two names behind one address share it for the TTL (the CDN case), and an opened address is open to every process of the sandbox, not only to the one that resolved the name. Also IPv4 only, and not yet exercised with a real host resolver, in containers or with the learning mode. Full list of limits and what the integration suite proves: [Unshare, names in `net=` rules](unshare.md#names-in-net-rules-net-resolveruntime).

### Host sockets under `/run`

`/run` holds sockets that reach the host: `/run/docker.sock`, and under `/run/user/<uid>` the session D-Bus bus
(which can start commands through `systemd --user`), the ssh and gpg agents. A read-only mount does not prevent
`connect()` on them. Each kernel provider keeps them out of reach in its own way:

- `bwrap` does not bind `/run`; it binds only the target of `/etc/resolv.conf` when that file points under `/run`
  (systemd-resolved).
- `unshare` builds a fresh root that has no `/run` from the host.
- `firejail` refuses the creation of any Unix socket; the distribution's `disable-common.inc` blacklist of
  `docker.sock` is only a second line.
- `landlock` does **not** keep the named ones out: Landlock filters file access, not `connect()` on a Unix socket,
  so native code can reach the session D-Bus bus or `docker.sock`; the Python guard still refuses it. From ABI 6
  the abstract ones created outside the sandbox are refused. A documented limit: for untrusted native code, use
  `bwrap` or `unshare`.
- `qemu` runs a separate kernel: the host's `/run` is not visible.
- `gvisor` binds no `/run` and starts `runsc` with `--host-uds=none`, which refuses any host Unix socket.
- `smolvm` runs a separate kernel on the root of its image: the host's `/run` is not visible, and only the one
  socket of the channel crosses the boundary.

An `expose-ro` or `expose-rw` rule naming a directory under `/run` gives those sockets back: write one only for a
socket the program really needs.

## Choosing by threat and cost

Pick the provider from what the code you run can do, then check what the isolation costs. The two layers add up:
keep `py-sandbox` on, and put one OS provider around it (see [Recommendations](#recommendations)).

| Threat | Typical code | Python layer | OS provider | What stops the attack |
|---|---|:---:|---|---|
| Mistakes, no attacker | Your own scripts | on | `subprocess` | Process separation and the guards. No OS boundary |
| Hostile Python, no native code | LLM-generated code, plugins | on | `landlock` (default) | The Python guards, plus a kernel ruleset on files and TCP ports |
| Hostile native code | Dependencies with C extensions, `ctypes`, database drivers | on | `bwrap` or `unshare` | Mount and network namespaces: a path that is not exposed does not exist, the network is filtered |
| Hostile native code, kernel exploits | Code that may attack the kernel itself | on | `gvisor` | The guest talks to a user-space kernel (Sentry), which makes a small set of host system calls |
| Worst case, or another CPU | Code you cannot reason about | on | `qemu` | A VM with its own Linux kernel: the host kernel is out of the guest's reach |
| Same as `qemu`, with a smaller virtual machine | Code you cannot reason about, on Linux x86_64, with at most eight host shares | on | `qemu-microvm` | A VM with its own Linux kernel, booted directly, with virtio-mmio devices only and no PCI or ACPI. Same isolation class as `qemu`, not a stronger one, and not faster to start |

`firejail` is a variant of the namespace row for hosts that already have it: it adds resource limits and a seccomp
filter. `sandbox-exec` (macOS) and `appcontainer` (Windows) are the choices on those systems.

### What each costs

Measured on one host with `py-sandbox=false`, one run each. Start-up counts the Python interpreter (0.13 s with
`os-sandbox=none`). Read orders of magnitude, not a benchmark: run your own workload.

| Provider | Start-up | 50 000 `os.stat` | Needs | Network filter |
|---|---:|---:|---|:---:|
| `none` | 0.13 s | 0.02 s | Nothing | ❌ |
| `subprocess` | 0.30 s | 0.02 s | Nothing | ❌ |
| `landlock` | 0.30 s | 0.02 s | Linux 6.7+ (Landlock ABI v4) | TCP ports |
| `bwrap` | 0.31 s | 0.03 s | `bwrap`, user namespaces; filtering also `slirp4netns`, `iptables` | ✅ |
| `firejail` | 0.51 s | 0.02 s | `firejail` | ✅ |
| `unshare` | 1.43 s | 0.03 s | User namespaces, `slirp4netns`, `iptables` | ✅ |
| `gvisor` (`systrap`) | 0.74 s | 0.16 s | `runsc`, `slirp4netns`, `iptables`, `/dev/net/tun` | ✅ |
| `smolvm` | 1.0 s | not measured | `smolvm`, `/dev/kvm`, a guest image (`make build-image-smolvm`) | ✅ |
| `qemu` | 12.8 s | 0.06 s | `qemu-system`; KVM makes it faster | ✅ |
| `qemu-microvm` | 20.4 s KVM<br/>110.3 s TCG | — | Linux x86_64, `qemu-system-x86_64`, `7zip`; KVM recommended | ✅ |

Three consequences:

- `gvisor` pays on system calls, not on computation: code that stays in the interpreter runs at the speed of the
  others, while a loop of `stat`, `open` or socket calls is 6 to 8 times slower. Its `ptrace` and `kvm` platforms are
  slower still on this host (see [gVisor](gvisor.md)).
- `qemu` and `qemu-microvm` pay once, at start-up. Keep the sandbox alive across calls (`with sandboxes():`) instead of starting one per
  call. Measured here, `qemu-microvm` starts slower than `qemu` (20.4 s with KVM and 110.3 s without, against 12.8 s for `qemu` in the table above):
  choose it for its smaller device model, not for speed, and prefer `qemu` when the program needs more than eight
  host shares. A TCG run carries no KVM isolation claim (see [QEMU microvm](qemu-microvm.md#limits)).
- `landlock`, `bwrap` and `firejail` cost almost nothing, which is why the default is not the strongest provider: go
  up only when the threat in the first table calls for it.

### In Docker, Podman and Kubernetes

A container adds a second boundary around the provider and takes nothing away from it.

- `landlock`, `qemu` and `qemu-microvm` run without extra privilege; mount `/dev/kvm` to a container when acceleration is available.
- `qemu` and `qemu-microvm` use KVM only when the profile allows it (`qemu.use_kvm`, true by default) **and** the
  process can read `/dev/kvm`. Otherwise QEMU runs fully emulated (TCG), with no error and no profile change:
  - **KVM**: Docker and Podman, with `--device /dev/kvm --group-add <gid of /dev/kvm>`, privileged or not; a Kubernetes
    pod that mounts the device (`hostPath`, `CharDevice`). The project's Kubernetes tests mount it only in the
    privileged row; an unprivileged pod with the device is not tested.
  - **TCG**: a container started without the device, an ordinary Kubernetes pod, a host without `/dev/kvm`, or
    `qemu.use_kvm=false`.
  - **Cost of TCG**: the guest answers after about 125s, against about 22s for a whole run under KVM, and slower on a
    loaded host. The daemon's start deadline follows the acceleration in use, so nothing is needed in the profile:
    `qemu.start_timeout` defaults to 90s with KVM and 300s emulated (see [qemu.md](qemu.md)).
  - **Container tests**: a Docker or Podman run may take 120s, or 900s for a `qemu` or `qemu-microvm` row that is
    given no `/dev/kvm` (the same 900s as the Kubernetes exec, `K8S_QEMU_EXEC_TIMEOUT`). `CONTAINER_RUN_TIMEOUT`
    overrides both. These are the test suite's limits, not the product's.
- `smolvm` needs no privilege in a container, only `/dev/kvm` and a non-root user of its group: a root caller is
  lowered by smolvm and its VMM then loses the device, even with `--privileged`. Docker: `--device /dev/kvm
  --group-add <gid> --user <uid>`. Rootless Podman maps the groups of the host to `nobody`, so it also needs
  `--userns=keep-id`. A Kubernetes pod gets the device from a device plugin (`resources.limits`), with no
  `securityContext`; a hostPath mount of `/dev/kvm` works in a privileged pod. The 9p mount of minikube cannot be shared
  with a guest (its server fails on the directory reads), so the project's pod tests copy what they need first. See
  [smolvm.md](smolvm.md).
- `bwrap` and `unshare` create namespaces of their own, which the default container confinement refuses:
  lower it as each provider page describes, or use `--privileged`.
- `gvisor` runs in Docker, Podman and Kubernetes. It adapts to where it runs by choosing how `runsc` hooks the guest's
  system calls (`gvisor.platform`): the default `systrap` uses a seccomp filter and needs neither KVM nor a VM, so it
  works inside a container. It does need `/dev/net/tun` and a lowered confinement: Docker `--privileged`, or
  `--device /dev/net/tun` with `seccomp` and `apparmor` unconfined; rootless Podman `--device /dev/net/tun` and
  `--cap-add NET_ADMIN`; a Kubernetes pod with `SYS_ADMIN` and `NET_ADMIN` and `Unconfined` seccomp and AppArmor
  profiles (see [gvisor.md](gvisor.md)).
- `firejail` does not run in a container, even with `--privileged`.
- A container does not replace the provider: without one, the sandboxed code is separated from the container by the
  Python layer alone.

## Recommendations

- Keep the generated default (`landlock` where the kernel supports it, `subprocess` otherwise) unless you need a specific provider; for untrusted native code, prefer `bwrap` or `unshare`.
- Nest an OS provider around the py-sandbox rather than replacing it: the union of both layers is your actual protection.
- Keep the Python layer on. Set `py-sandbox=False` only when the sandboxed code is trusted not to attack the interpreter itself.
- On a managed Kubernetes cluster, verify that the node kernel exposes Landlock before relying on it.
- Leave the result guard on. Turn it off with `remote-result-guard=false` only if a legitimate return value is wrongly rejected.
- After a learning phase, add *manually* the network rules that compiled code needs: learning runs under `subprocess` and cannot see them.

## References

- [bubblewrap](https://github.com/containers/bubblewrap), [firejail](https://github.com/netblue30/firejail), [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html), [landlock](https://landlock.io/), [qemu](https://www.qemu.org/), [gVisor](https://gvisor.dev)
- Provider pages: [subprocess](subprocess.md), [bwrap](bwrap.md), [firejail](firejail.md), [unshare](unshare.md), [landlock](landlock.md), [qemu](qemu.md), [qemu-microvm](qemu-microvm.md), [gvisor](gvisor.md), [smolvm](smolvm.md)
- [Database drivers](database.md), [transport unpickle guard](transport-unpickle-guard.md)
