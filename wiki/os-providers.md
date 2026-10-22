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
| Resource limits and seccomp | `firejail` |
| Inside Docker or Podman | `landlock` or `qemu` unprivileged; `unshare` or `bwrap` with `--privileged` |
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
| sandbox-exec | [here](sandbox-exec.md) | • Seatbelt path and port filtering<br/>• Deprecated by Apple<br/>• No remote host/IP filtering | Legacy macOS-only profile launcher. |

The `none` column means plain Python with no sandbox. `py-sandbox` shows the Python layer. Each OS column shows that provider's controls; it does not include Python controls. In practice, OS providers wrap the Python layer.

A ❌ means the provider does not enforce that control. The Python layer may still enforce it. For example, Landlock cannot filter imports, but blocks compiled code and direct syscalls. Combined controls provide the effective protection.

[`sandbox-exec`](sandbox-exec.md) is the macOS provider. Apple has deprecated the command, and it creates no namespace, so it is not a VM boundary. See [the provider page](sandbox-exec.md) before selecting it.

| Guard                    | none | py-sandbox | landlock  |  unshare  |   bwrap   | firejail |       qemu       | sandbox-exec |
|--------------------------|:----:|:----------:|:---------:|:---------:|:---------:|:------:|:----------------:| :----------: |
| Isolation                |  ❌   |  Process   | Linux ABI | Namespace | Namespace | Namespace | VM+<br/>emulator | Seatbelt |
| Python code              |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ |
| Compiled code            |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| env                      |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| import                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ |
| expose-ro/rw=path        |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| ignore=*                 |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| python-api=*             |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| eval-*                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         | ❌ |
| **Network**              |      |            |           |           |           |        |                  |  |
| • TCP                    |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| • UDP                    |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| • host                   |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         | ❌ |
| • port                   |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| OS-sandbox               |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| Vm compatible            |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         | ✅ |
| **Docker / Podman**      |      |            |           |           |           |        |                  |  |
| • unprivileged           |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | n/a |
| • --privileged           |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ✅         | n/a |
| **Kubernetes**           |      |            |           |           |           |        |                  |  |
| • unprivileged pod       |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         | n/a |
| • SYS_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | n/a |
| • NET_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         | n/a |
| **Extra**                |      |            |           |           |           |        |                  |  |
| • Resource limits        |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |     ✅  |        ✅         | ❌ |
| • Seccomp                |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |   ✅    |        ✅         | ❌ |
| • Latency                | <1s  |    <1s     |    <1s    |    <1s    |    <1s    |    <1s |      >20s        | <1s |

QEMU passes the `readonly=on` export option for `expose-ro` mounts; an end-to-end native guest write regression test covers this behavior. Landlock denies TCP bind/connect by default on ABI v4+, but cannot filter UDP and is unavailable below ABI v4. See [QEMU security limitations](qemu.md#security-limitations) and [Landlock limits](landlock.md#limits).

On `sandbox-exec`, the `• host` row is ❌ because Seatbelt filters by protocol and port only: `net=ALLOW|TCP|203.0.113.7|443|OUT` becomes "TCP port 443, any remote host". Only the Python socket guard still checks the host, so with `py-sandbox=false` native code reaches any host on an allowed port. A port rule is still enforced by the kernel. When DNS (UDP 53) is allowed, Seatbelt also needs an unscoped local UDP inbound permission for the replies. Details: [network limitations](sandbox-exec.md#network-limitations).

`ignore=` is enforced differently by each technology: **py-sandbox** and **firejail** make the path disappear (`FileNotFoundError`), **unshare** and **sandbox-exec** have the OS refuse it (`PermissionError`), and **bwrap** and **qemu** mask it, so a read succeeds and returns nothing. **landlock** denies access to a path but cannot hide one, so it has no equivalent: with `--py-sandbox=False` an ignored file stays readable there.

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

An `expose-ro` or `expose-rw` rule naming a directory under `/run` gives those sockets back: write one only for a
socket the program really needs.

## Paranoia level
Depending on your level of paranoia, you can choose a suitable approach.

| Paranoia | Py-sandbox       | os-sandbox     | docker/pod | --privileged |
|:--------:|------------------|----------------|:----------:|:------------:|
|    0     | python           | None           |     No     |              |
|    1     | python-sb        | subprocess     |     No     |              |
|    2     | with sandboxes() | subprocess     |     No     |              |
|    3     | python-sb        | landlock       |     No     |              |
|    4     | with sandboxes() | landlock       |     No     |              |
|    5     | python-sb        | unshare        |     No     |              |
|    6     | with sandboxes() | unshare        |     No     |              |
|    7     | python-sb        | bwrap/firejail |     No     |              |
|    8     | with sandboxes() | bwrap/firejail |     No     |              |
|    9     | python-sb        | qemu + kvm     |     No     |              |
|    10    | with sandboxes() | qemu + kvm     |     No     |              |
|    11    | python-sb        | landlock       |    Yes     |      No      |
|    12    | with sandboxes() | landlock       |    Yes     |      No      |
|    13    | python-sb        | unshare        |    Yes     |     Yes      |
|    14    | with sandboxes() | unshare        |    Yes     |     Yes      |
|    15    | python-sb        | bwrap/firejail |    Yes     |     yes      |
|    16    | with sandboxes() | bwrap/firejail |    Yes     |     yes      |
|    17    | python-sb        | qemu           |    Yes     |      no      |
|    18    | with sandboxes() | qemu           |    Yes     |      no      |

## Recommendations

- Keep the generated default (`landlock` where the kernel supports it, `subprocess` otherwise) unless you need a specific provider; for untrusted native code, prefer `bwrap` or `unshare`.
- Nest an OS provider around the py-sandbox rather than replacing it: the union of both layers is your actual protection.
- Keep the Python layer on. Set `py-sandbox=False` only when the sandboxed code is trusted not to attack the interpreter itself.
- On a managed Kubernetes cluster, verify that the node kernel exposes Landlock before relying on it.
- Leave the result guard on. Turn it off with `remote-result-guard=false` only if a legitimate return value is wrongly rejected.
- After a learning phase, add *manually* the network rules that compiled code needs: learning runs under `subprocess` and cannot see them.

## References

- [bubblewrap](https://github.com/containers/bubblewrap), [firejail](https://github.com/netblue30/firejail), [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html), [landlock](https://landlock.io/), [qemu](https://www.qemu.org/)
- Provider pages: [bwrap](bwrap.md), [firejail](firejail.md), [unshare](unshare.md), [landlock](landlock.md), [qemu](qemu.md)
- [Database drivers](database.md), [transport unpickle guard](transport-unpickle-guard.md)
