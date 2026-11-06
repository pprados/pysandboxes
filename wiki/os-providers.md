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
| Default on Linux: nothing to install, no privilege, files and TCP ports | `landlock` |
| Untrusted native code, or host and UDP filtering | `bwrap` or `unshare` |
| Strongest separation, in a VM (more than 20 s to start) | `qemu` |
| Compiled code or kernel exploits, user-space kernel, starts in about a second | `gvisor` |
| Resource limits and seccomp | `firejail` |
| Inside Docker or Podman | `landlock` or `qemu` unprivileged; `unshare`, `bwrap` or `gvisor` with `--privileged` |
| Files and ports on macOS (Seatbelt, no host filtering) | [`sandbox-exec`](sandbox-exec.md) |
| Process separation only, no OS boundary (also on macOS, and the only choice on Windows) | `subprocess` |

Two limits to know before choosing `landlock`: it denies a path but cannot hide it, and it does not protect the host's named Unix sockets (see [Host sockets under `/run`](#host-sockets-under-run)). Against untrusted native code, prefer `bwrap` or `unshare`.

## All providers

The providers that can wrap the Python sandbox are:

| Technology                                                      | Implementation<br/>&amp;<br/>Configuration | Specifics                                                                    | Description                                                                                                                              |
|-----------------------------------------------------------------|--------------------------------------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| subprocess                                                      |                                            | • no complementary security                                                  |                                                                                                                                          |
| [bwrap](https://github.com/containers/bubblewrap)               | [here](bwrap.md)                      | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [firejail](https://github.com/netblue30/firejail)               | [here](firejail.md)                   | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html) | [here](unshare.md)                    | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels using `unshare`, `slirp4netns` and `iptables`. |
| [landlock](https://landlock.io/)                                | [here](landlock.md)                   | • Directory access<br/>• Network TCP port filtering                          | This is a technology that allows an auto isolation inside a Linux process.                                                               |
| [qemu](https://www.qemu.org/)                            | [here](qemu.md)                       | • Total emulation of OS and CPU                                              | No need of privilege. Use KVM if it's possible, else use the emulation.                                                                  |
| [gvisor](https://gvisor.dev)                             | [here](gvisor.md)                     | • User-space kernel (Sentry)<br/>• Disk mapping<br/>• File filtering<br/>• Network filtering | `runsc` in a private network namespace filtered by `iptables`, with `slirp4netns`. |
| sandbox-exec | [here](sandbox-exec.md) | • Seatbelt path and port filtering<br/>• Deprecated by Apple<br/>• No remote host/IP filtering | Legacy macOS-only profile launcher. |
| [appcontainer](appcontainer.md) | [here](appcontainer.md) | • File ACLs<br/>• AppContainer network capabilities<br/>• Job Object | Windows-only provider; its administrator and standard-user suites pass, and `cross-os.yml` runs them on the Windows runner. |

The `none` column means plain Python with no sandbox. `py-sandbox` shows the Python layer. Each OS column shows that provider's controls; it does not include Python controls. In practice, OS providers wrap the Python layer.

A ❌ means the provider does not enforce that control. The Python layer may still enforce it. For example, Landlock cannot filter imports, but blocks compiled code and direct syscalls. Combined controls provide the effective protection.

[`sandbox-exec`](sandbox-exec.md) is the macOS provider. Apple has deprecated the command, and it creates no namespace, so it is not a VM boundary. See [the provider page](sandbox-exec.md) before selecting it.

| Guard                    | none | py-sandbox | landlock  |  unshare  |   bwrap   | firejail |       qemu       | gvisor | sandbox-exec | appcontainer¹ |
|--------------------------|:----:|:----------:|:---------:|:---------:|:---------:|:------:|:----------------:|:--------:| :----------: |:-----------:|
| Isolation                |  ❌   |  Process   | Linux ABI | Namespace | Namespace | Namespace | VM+<br/>emulator | User-space<br/>kernel | Seatbelt | AppContainer |
| Python code              |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ |
| Compiled code            |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ |
| env                      |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ |
| import                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ |
| expose-ro/rw=path        |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ |
| ignore=*                 |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | Partial² |
| python-api=*             |  ❌   | ✅ |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  |  ❌  |
| eval-*                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ | ❌ | ❌ |
| **Network**              |      |            |           |           |           |        |                  |  |  |  |
| • TCP                    |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | Partial³ |
| • UDP                    |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | Partial³ |
| • host                   |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ❌ | ❌³ |
| • port                   |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ❌³ |
| OS-sandbox               |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ |
| Vm compatible            |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ | ✅ | ✅ |
| **Docker / Podman**      |      |            |           |           |           |        |                  |  |  |  |
| • unprivileged           |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | ❌ | n/a | n/a |
| • --privileged           |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ✅         | ✅ | n/a | n/a |
| **Kubernetes**           |      |            |           |           |           |        |                  |  |  |  |
| • unprivileged pod       |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | ❌ | n/a | n/a |
| • SYS_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | ✅ | n/a | n/a |
| • NET_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | ✅ | n/a | n/a |
| **Extra**                |      |            |           |           |           |        |                  |  |  |  |
| • Resource limits        |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |     ✅  |        ✅         | ❌ | ❌ | ❌ |
| • Seccomp                |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |   ✅    |        ✅         | ❌ | ❌ | n/a |
| • Latency                | <1s  |    <1s     |    <1s    |    <1s    |    <1s    |    <1s |      >20s        | ~1s | <1s | Pending |

¹ `appcontainer` is Windows-only: the Docker and Kubernetes rows do not apply. ² `ignore=` covers only paths present at launch, and their names may remain listable. ³ AppContainer denies outbound network access by default. An `ALLOW` `net=` rule grants a broad public-Internet or private-network capability; AppContainer itself does not filter host, port, protocol, or loopback. The Python guard checks the first three only while enabled, so native code can bypass those checks. Loopback is blocked by AppContainer even when a rule allows it.

QEMU passes the `readonly=on` export option for `expose-ro` mounts; an end-to-end native guest write regression test covers this behavior. Landlock denies TCP bind/connect by default on ABI v4+, but cannot filter UDP and is unavailable below ABI v4. See [QEMU security limitations](qemu.md#security-limitations) and [Landlock limits](landlock.md#limits).

On `sandbox-exec`, the `• host` row is ❌ because Seatbelt filters by protocol and port only: `net=ALLOW|TCP|203.0.113.7|443|OUT` becomes "TCP port 443, any remote host". Only the Python socket guard still checks the host, so with `py-sandbox=false` native code reaches any host on an allowed port. A port rule is still enforced by the kernel. When DNS (UDP 53) is allowed, the rule becomes a grant on the system resolver socket (`mDNSResponder`), not a UDP rule. Details: [network limitations](sandbox-exec.md#network-limitations).

`ignore=` is enforced differently by each technology: **py-sandbox** and **firejail** make the path disappear (`FileNotFoundError`), **unshare** and **sandbox-exec** have the OS refuse it (`PermissionError`), and **bwrap**, **qemu** and **gvisor** mask it, so a read succeeds and returns nothing. **landlock** denies access to a path but cannot hide one, so it has no equivalent: with `--py-sandbox=False` an ignored file stays readable there.

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

Not supported by this layer: Windows named pipes (uvicorn cannot serve on them) and anonymous pipes (no accept loop).

### How host names of `net=` rules are resolved: `net-resolve`

`net-resolve=pinned|runtime` picks when the host name of a `net=` rule (`net=ALLOW|TCP|api.example.com|443|OUT`) becomes addresses. The default is not decided yet; without the key the value is `pinned`.

- `pinned` resolves the name once, at start, and freezes the addresses in the ruleset and in `/etc/hosts`. A name whose addresses rotate is refused once they change.
- `runtime` resolves the name when the sandboxed program asks. The sandbox DNS (`10.0.2.3`) is redirected to a filtering resolver on the host, which answers only the names a rule allows (`NXDOMAIN` otherwise), opens the addresses of an allowed answer in the sandbox firewall before it replies, and closes them when their TTL (clamped to 60 s to 1 h) is over. The firewall keeps the protocols and ports of the rule, a static `DENY` keeps precedence, and a resolver the program names itself (`8.8.8.8`, DoT, DoH to an unlearned address) meets the default `DROP`.

`runtime` is available for `unshare` only, and needs `nsenter` and `iptables` on the host. Any other provider rejects it with a configuration error rather than falling back to `pinned`. A rule names a host as `name` (the name and its subdomains), `=name` (the name only) or `*.name` (subdomains only). Limits: two names behind one address share it for the TTL (the CDN case), and an opened address is open to every process of the sandbox, not only to the one that resolved the name. Also IPv4 only, and not yet exercised with a real host resolver, in containers or with the learning mode. Full list of limits and what the integration suite proves: [Unshare, names in `net=` rules](unshare.md#names-in-net-rules-net-resolveruntime).

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
| `qemu` | 12.8 s | 0.06 s | `qemu-system`; KVM makes it faster | ✅ |

Three consequences:

- `gvisor` pays on system calls, not on computation: code that stays in the interpreter runs at the speed of the
  others, while a loop of `stat`, `open` or socket calls is 6 to 8 times slower. Its `ptrace` and `kvm` platforms are
  slower still on this host (see [gVisor](gvisor.md)).
- `qemu` pays once, at start-up. Keep the sandbox alive across calls (`with sandboxes():`) instead of starting one per
  call.
- `landlock`, `bwrap` and `firejail` cost almost nothing, which is why the default is not the strongest provider: go
  up only when the threat in the first table calls for it.

### In Docker, Podman and Kubernetes

A container adds a second boundary around the provider and takes nothing away from it.

- `landlock` and `qemu` run without extra privilege.
- `bwrap`, `unshare` and `gvisor` create namespaces of their own, which the default container confinement refuses:
  lower it as each provider page describes, or use `--privileged`.
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
- Provider pages: [bwrap](bwrap.md), [firejail](firejail.md), [unshare](unshare.md), [landlock](landlock.md), [qemu](qemu.md), [gvisor](gvisor.md)
- [Database drivers](database.md), [transport unpickle guard](transport-unpickle-guard.md)
