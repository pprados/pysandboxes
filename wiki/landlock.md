# LandLock

## Definition

[LandLock](https://landlock.io/) is an OS-level sandboxing technology that works at the process level and needs no special privilege to be activated. Its first stable version (ABI v1) has been available since Linux kernel 5.13.

LandLock follows a **whitelist** approach: all access is denied by default. It can authorize read and write access to directories, and it can limit the listening or destination ports of network calls (TCP only). It cannot control destination IP addresses.

Its strength lies elsewhere: it works everywhere, without any privilege. The process itself decides which restrictions it applies, then activates them. Once they are active, it cannot escape them, and its child processes inherit the same constraints.

It needs no extra binary, which is why `os-sandbox=auto` (the template's default) picks it on Linux when the kernel supports it, falling back to `subprocess` otherwise. See [provider comparison](os-providers.md#os-sandbox-vs-py-sandbox).

## How the provider works

Unlike the other providers, nothing is set up on the host: the sandbox process restricts **itself**. For this, `LandlockSSEDaemon` starts an ordinary child process. Before running your code, that process translates the **`expose-ro` / `expose-rw`** file rules into `path_beneath` rules and the **`net=`** socket rules into port rules, then applies the ruleset to itself with the `landlock_*` syscalls. From that point, the restrictions are irrevocable and inherited by any child. The host talks to the sandbox over SSE, as with the other providers.

## Access modes

| Mode | Rights granted |
| ---- | -------------- |
| **`expose-ro`** | execute, read file, list directory. |
| **`expose-rw`** | everything in `ro`, plus write file, remove file/dir, create (reg/dir/sym/char/sock/fifo/block), `REFER` (rename/link across directories), `TRUNCATE` (`creat`, `open(O_TRUNC)`, `ftruncate`). |

There is no useful **write-only** mode. In effect, a directory needs `READ_DIR` to be listed and `READ_FILE` to be read, so `rw` always includes `ro`, and writable paths behave like ordinary writable directories.

## Kernel ABI and degraded modes

The provider reads the kernel ABI at startup and masks the rights the running kernel does not know. An older kernel therefore still works, with reduced semantics, rather than failing.

| Feature | Required ABI | Kernel | Behaviour below that version |
| ------- | ------------ | ------ | ---------------------------- |
| Filesystem rules | v1 | 5.13+ | Landlock unavailable, see below. |
| `REFER` (rename/link across directories) | v2 | — | Right is masked: rename and link only within the same directory. |
| `TRUNCATE` | v3 | 6.2+ | Right is masked: `open(O_TRUNC)` or `creat` may fail on an existing file. |
| Network rules (TCP bind/connect by port) | v4 | 6.7+ | **Socket rules are not enforced at OS level.** The py-sandbox layer still applies them. |

If the ruleset cannot be applied at all (for example `ENOSYS` on a kernel without Landlock), the sandbox process **logs the error and exits**. It never runs unprotected in silence.

## Limits

- **No control over destination IP addresses**, only TCP ports. For example, a rule such as `net=ALLOW|tcp|www.google.com|443|OUT` is reduced to `(443, connect)`: the host part is dropped when the ruleset is built, and filtering by host relies on the py-sandbox layer alone.
- **Only `ALLOW` rules are translated.** `DENY` rules are skipped when the ruleset is built. This is safe, since Landlock denies everything not explicitly allowed. Note, however, that a `DENY` carving an exception out of a wider `ALLOW` is then enforced by the py-sandbox layer only.
- **UDP is not covered**: Landlock network rules are TCP-only (`BIND_TCP` / `CONNECT_TCP` are the only two network rights).
- `chmod` and `chown` are not restricted by Landlock; standard DAC permissions still apply.
- **No process, IPC or PID isolation**: Landlock restricts the filesystem and TCP ports, nothing else.
- **Named Unix sockets of the host stay reachable.** Landlock filters file access, not `connect()` on a Unix
  socket: native code can reach `/run/user/<uid>/bus` (the session D-Bus bus, which starts commands through
  `systemd --user`), `docker.sock`, the ssh and gpg agents, an X11 or Wayland display, a tmux server. The Python
  layer refuses it (a Unix connection needs `expose-rw` on the socket), `ctypes` or a compiled extension does not.
  From ABI 6, abstract Unix sockets created outside the sandbox are refused.

## Running the provider

The first approach runs the provider directly on the host. It needs no package and no privilege, only a kernel recent enough (see [Prerequisites](#prerequisites)).

The second approach runs it inside Docker or Podman. LandLock is compatible with both, since it needs no privilege. The project ships a provider image, `python-sb-landlock` (tagged e.g. `:latest` or `:3.12`), built from the project root with:

```bash
make build-image-landlock
```

```bash
docker \
  run -it --rm \
  -v "$(pwd)":/app \
  -w /app \
  python-sb-landlock:latest \
  sh -c 'pip install -e . && OS_SANDBOX=landlock python-sb -m tests.integration_tests.tst_usage'
```

Note that the ABI available inside the container is the **host** kernel's: a container cannot provide a Landlock version the host does not have.

## Specific parameters

There are no specific parameters for *LandLock*. Unlike `bwrap.<option>=`, `firejail.<option>=`, `unshare.<option>=` or `qemu.<key>=`, no `landlock.*` line is interpreted: the ruleset is derived entirely from the `expose-ro` / `expose-rw` and `net=` rules.

## Prerequisites

- Linux kernel **5.13+** for filesystem rules, **6.7+** for network rules.
- No package to install and no privilege to grant: Landlock is a kernel LSM used through syscalls.
- Check that Landlock is enabled on your host with:

```bash
cat /sys/kernel/security/lsm   # must list "landlock"
```

This tells you whether the LSM is active, not which ABI it exposes. The provider queries the exact ABI at startup with `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` and adapts as described above.

## Recommendations

- Choose LandLock when no privilege can be granted, on the host or in a container: it needs neither a package nor a privilege, only a recent kernel.
- Make sure the host kernel is **6.7+** before relying on the `net=` rules at OS level. Below that version, only the py-sandbox layer enforces them.
- Do not count on LandLock to filter by host, by IP address, or over UDP. When you need IP-level filtering at OS level, use [unshare](unshare.md), [bwrap](bwrap.md) or [firejail](firejail.md).
- Keep the `DENY` exceptions to a minimum: LandLock does not see them.
- For code that may run native code you do not trust, prefer [bwrap](bwrap.md) or [unshare](unshare.md): their
  root holds none of the host's sockets.

## References

- [LandLock](https://landlock.io/)
- [unshare provider](unshare.md), [bwrap provider](bwrap.md), [firejail provider](firejail.md)
