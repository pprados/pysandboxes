# OS-level sandbox providers

## OS-sandbox vs Py-sandbox

Our solution offers multiple layers of security:

- a sandbox at the Python API level (**py-sandbox**)
- another sandbox at the OS level (**os-sandbox**)

The Python sandbox (*py-sandbox*) can limit malicious usage via Python code, but it cannot prevent access via compiled C/C++/Rust code, or via direct calls to the kernel. For example, database access is often done via compiled C drivers (See [here](database.md) for more details). Similarly, a malicious code, with a little persistence, can manage to escape the Python sandbox. The goal is not to protect against a dependency imported into your project without ensuring it is safe. **We want to prevent abusive use of our code.**

Therefore, to protect against a scenario that escapes **Py-Sandboxes**, it is possible to select a complementary technology that provides protection at the OS level. Depending on the available and selected technologies, the limitations will be more or less the same as with **py-sandbox**. You will not find specific Python limitations, such as the module whitelist.

We offer several implementations to encapsulate the Python sandbox:

| Technology                                                      | Implementation<br/>&amp;<br/>Configuration | Specifics                                                                    | Description                                                                                                                              |
|-----------------------------------------------------------------|--------------------------------------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| subprocess                                                      |                                            | • no complementary security                                                  |                                                                                                                                          |
| [bwrap](https://github.com/containers/bubblewrap)               | [here](bwrap.md)                      | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [firejail](https://github.com/netblue30/firejail)               | [here](firejail.md)                   | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels.                                               |
| [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html) | [here](unshare.md)                    | • Disk mapping (without rename)<br/>• File filtering<br/>• Network filtering | This is a technology that allows isolating a Linux process at the disk and network levels using `unshare`, `slirp4netns` and `iptables`. |
| [landlock](https://landlock.io/)                                | [here](landlock.md)                   | • Directory access<br/>• Network TCP port filtering                          | This is a technology that allows an auto isolation inside a Linux process.                                                               |
| [qemu](https://www.qemu.org/)                            | [here](qemu.md)                       | • Total emulation of OS and CPU                                              | No need of privilege. Use KVM if it's possible, else use the emulation.                                                                  |

*Other implementations will be added soon*

How to read the matrix below. The `none` column is the baseline: plain Python, no sandbox at all. The `py-sandbox` column is the Python layer on its own. Every other column lists what that OS technology enforces **on its own** too, whereas in practice you nest it *around* the py-sandbox instead of replacing it.

So a ❌ means "*this technology does not deal with that concern*", never "*that concern is left unprotected*". Choosing landlock, for instance, does not stop the Python guards from filtering `import` or sensitive API calls: landlock simply has no notion of Python, and in exchange it covers what the Python layer cannot reach, namely compiled code and direct syscalls. Read each OS column as what you *add* on top of the Python layer, and the union of the two as your actual protection.

| Guard                    | none | py-sandbox | landlock  |  unshare  |   bwrap   | firejail |       qemu       |
|--------------------------|:----:|:----------:|:---------:|:---------:|:---------:|:------:|:----------------:|
| Isolation                |  ❌   |  Process   | Linux ABI | Namespace | Namespace | Namespace | VM+<br/>emulator |
| Python code              |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         |
| Compiled code            |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| env                      |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| import                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         |
| expose-ro/rw=path        |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| ignore=*                 |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         |
| python-api=*             |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| eval-*                   |  ❌   |     ✅      |     ❌     |     ❌     |     ❌     |     ❌  |        ❌         |
| **Network**              |      |            |           |           |           |        |                  |
| • TCP                    |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| • UDP                    |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         |
| • host                   |  ❌   |     ✅      |     ❌     |     ✅     |     ✅     |     ✅  |        ✅         |
| • port                   |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| OS-sandbox               |  ❌   |     ❌      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| Vm compatible            |  ❌   |     ✅      |     ✅     |     ✅     |     ✅     |     ✅  |        ✅         |
| **Docker / Podman**      |      |            |           |           |           |        |                  |
| • unprivileged           |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         |
| • --privileged           |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ✅         |
| **Kubernetes**           |      |            |           |           |           |        |                  |
| • unprivileged pod       |  ✅   |     ✅      |     ✅     |     ❌     |     ❌     |     ❌  |        ✅         |
| • SYS_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         |
| • NET_ADMIN              |  ✅   |     ✅      |     ✅     |     ✅     |     ✅     |     ❌  |        ❌         |
| **Extra**                |      |            |           |           |           |        |                  |
| • Resource limits        |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |     ✅  |        ✅         |
| • Seccomp                |  ❌   |     ❌      |     ❌     |     ❌     |     ❌     |   ✅    |        ✅         |
| • Latency                | <1s  |    <1s     |    <1s    |    <1s    |    <1s    |    <1s |      >20s        |

`ignore=` is enforced differently by each technology: **py-sandbox** and **firejail** make the path disappear (`FileNotFoundError`), **unshare** has the OS refuse it, and **bwrap** and **qemu** mask it, so a read succeeds and returns nothing. **landlock** denies access to a path but cannot hide one, so it has no equivalent: with `--py-sandbox=False` an ignored file stays readable there.

**landlock** under Kubernetes needs no capability at all, which is why its three Kubernetes rows are identical: unlike **unshare** and **bwrap**, it never asks the pod for `SYS_ADMIN` or `NET_ADMIN`, it restricts itself from the inside. Its single requirement sits elsewhere, on the *node*: the kernel must expose Landlock (5.13+ for filesystem rules, 6.7+ for network rules), and the ABI seen inside the pod is the node's, not the image's. On a managed cluster, where the node kernel is not yours to choose, verify it before relying on it.

On the **Extra** rows, **bwrap** is `❌` twice, for two different reasons. It has no resource-limit option at all, and the `bwrap.<option>=` passthrough can only forward flags bubblewrap already understands. Seccomp it *does* expose, but only as `--seccomp FD` / `--add-seccomp-fd FD`, which expect a file descriptor carrying a compiled BPF program; a textual configuration line cannot provision one, so the feature is out of reach here rather than missing from the tool.

For **qemu**, the resource that is bounded is memory: `qemu.memory` caps guest RAM (2048 MiB by default). The vCPU count is not exposed, and unlike `bwrap.*`, unknown `qemu.*` keys are not forwarded to the command line, only the documented ones are read.

A `❌` in the **py-sandbox** column is a deliberate posture, not a gap: with `py-sandbox=False` (or `--py-sandbox=False`) the Python layer is switched off on purpose, so `python-api=`, `eval-*`, `import=`, the Python-code guard and, on **landlock**, `ignore=` stop being enforced. Only the OS layer of the chosen technology remains. Use it when the sandboxed code is trusted not to attack the interpreter itself and you want the OS boundary alone; keep the Python layer on otherwise.

The parent deserializes what the sandboxed child returns over the local SSE transport. Reconstructing a returned object can run arbitrary code in the parent, outside the sandbox, so that channel is filtered by a restricted unpickler. On the result channel the guard is a fail-open denylist of dangerous gadgets, on by default; turn it off with `remote-result-guard=false` only if a legitimate return value is wrongly rejected. It affects only the result denylist: the opcode prescan, the anti-DoS budgets, and the exception-channel guard stay on regardless.

On the exception channel the guard is fail-closed, and an exception's state routinely holds a type it refuses — `httpx.ConnectError` carries the `httpx.Request` it failed on. So the child also sends a descriptor of the exception (class, message, denials), and the parent falls back to it rather than losing the refusal. An exception that crosses that way keeps its class, its message, its traceback and `sandbox_denials(e)`, but arrives **without its attributes**: `except httpx.ConnectError as e` still works, `e.request` does not. See [here](transport-unpickle-guard.md).



> During the learning phase, `os-sandbox` is forced to `subprocess`.

> Note that a network constraint may not be detected during learning if the call is made by compiled code. The **OS-sandbox** configuration will not allow the connection. Simply add the missing rule *manually*. It will be added when the **os-sandbox** is launched.

To select the **OS-sandbox** provider, set the parameter `os-sandbox` in the config file, or set the environment variable `OS_SANDBOX`.

```shell
OS_SANDBOX=unshare python-sb -m my-module
```

> Need help: can you propose a PR to integrate some solution for Apple OS ?

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

- Nest an OS provider around the py-sandbox rather than replacing it: the union of both layers is your actual protection.
- Keep the Python layer on. Set `py-sandbox=False` only when the sandboxed code is trusted not to attack the interpreter itself.
- On a managed Kubernetes cluster, verify that the node kernel exposes Landlock before relying on it.
- Leave the result guard on. Turn it off with `remote-result-guard=false` only if a legitimate return value is wrongly rejected.
- After a learning phase, add *manually* the network rules that compiled code needs: learning runs under `subprocess` and cannot see them.

## References

- [bubblewrap](https://github.com/containers/bubblewrap), [firejail](https://github.com/netblue30/firejail), [unshare](https://man7.org/linux/man-pages/man2/unshare.2.html), [landlock](https://landlock.io/), [qemu](https://www.qemu.org/)
- Provider pages: [bwrap](bwrap.md), [firejail](firejail.md), [unshare](unshare.md), [landlock](landlock.md), [qemu](qemu.md)
- [Database drivers](database.md), [transport unpickle guard](transport-unpickle-guard.md)
