# LandLock

[LandLock](https://landlock.io/) is an OS-level sandboxing technology at the process level, requiring no special privileges to be activated. Its first stable version (ABI v1) has been available since Linux kernel version 5.13.

LandLock operates on a **"Whitelist"** approach, where all access is denied by default. It is capable of authorizing read and write access to directories and limiting listening or destination ports for network calls (TCP only).
As of the current version (ABI v5), it is not yet capable of controlling destination IP addresses.

Nevertheless, it offers the advantage of working everywhere without limitations. It requires no specific privileges to function. The process itself decides which restrictions it wishes to apply and activates them. Once activated, it cannot escape them. Child processes inherit the same constraints.

## Solution in brief

Unlike the other providers, nothing is set up on the host: the sandbox process restricts **itself**. `LandlockSSEDaemon` starts a normal child process which, before running your code, translates **`expose-ro` / `expose-rw`** file rules into `path_beneath` rules and **`net=`** socket rules into port rules, then applies the ruleset to itself with the `landlock_*` syscalls. From that point the restrictions are irrevocable and inherited by any child. The host talks to the sandbox via SSE, as with the other providers.

## Access modes

| Mode | Rights granted |
| ---- | -------------- |
| **`expose-ro`** | execute, read file, list directory. |
| **`expose-rw`** | everything in `ro`, plus write file, remove file/dir, create (reg/dir/sym/char/sock/fifo/block), `REFER` (rename/link across directories), `TRUNCATE` (`creat`, `open(O_TRUNC)`, `ftruncate`). |

There is no useful **write-only** mode: a directory needs `READ_DIR` to be listed and `READ_FILE` to be read, so `rw` always includes `ro` and writable paths behave like ordinary writable directories.

## Kernel ABI and degraded modes

The provider reads the kernel ABI at startup and masks the rights the running kernel does not know about, so an older kernel still works with reduced semantics rather than failing.

| Feature | Required ABI | Kernel | Behaviour below that version |
| ------- | ------------ | ------ | ---------------------------- |
| Filesystem rules | v1 | 5.13+ | Landlock unavailable, see below. |
| `REFER` (rename/link across directories) | v2 | — | Right is masked: rename and link only within the same directory. |
| `TRUNCATE` | v3 | 6.2+ | Right is masked: `open(O_TRUNC)` or `creat` may fail on an existing file. |
| Network rules (TCP bind/connect by port) | v4 | 6.7+ | **Socket rules are not enforced at OS level.** The py-sandbox layer still applies them. |

If the ruleset cannot be applied at all (for example `ENOSYS` on a kernel without Landlock), the sandbox process **logs the error and exits**; it does not silently run unprotected.

## Limits

- **No control over destination IP addresses**, only TCP ports. A rule such as `net=ALLOW|tcp|www.google.com|443|OUT` is reduced to `(443, connect)`: the host part is dropped when the ruleset is built. Filtering by host relies on the py-sandbox layer. Use **unshare**, **bwrap** or **firejail** when you need IP-level filtering at OS level.
- **Only `ALLOW` rules are translated.** `DENY` rules are skipped when building the ruleset — which is safe, since Landlock denies everything not explicitly allowed, but it means a `DENY` carving an exception out of a wider `ALLOW` is enforced by the py-sandbox layer only.
- **UDP is not covered**: Landlock network rules are TCP-only (`BIND_TCP` / `CONNECT_TCP` are the only two network rights).
- `chmod` and `chown` are not restricted by Landlock; standard DAC permissions still apply.
- No process, IPC or PID isolation: Landlock restricts filesystem and TCP ports, nothing else.

## Using with Docker/Podman

LandLock is compatible with Docker and Podman: it needs no privilege, only a host kernel recent enough. The project ships a provider image, `python-sb-landlock` (tagged e.g. `:latest` or `:3.12`), built from the project root with:

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

The ABI available inside the container is the **host** kernel's one: a container cannot provide a Landlock version the host does not have.

## Specific Parameters

There are no specific parameters available for *LandLock*. Unlike `bwrap.<option>=`, `firejail.<option>=`, `unshare.<option>=` or `qemu.<key>=`, no `landlock.*` line is interpreted: the ruleset is derived entirely from the `expose-ro` / `expose-rw` and `net=` rules.

## Prerequisites

- Linux kernel **5.13+** for filesystem rules, **6.7+** for network rules.
- No package to install and no privilege to grant: Landlock is a kernel LSM used through syscalls.
- Check that Landlock is enabled on your host with:

```bash
cat /sys/kernel/security/lsm   # must list "landlock"
```

This tells you whether the LSM is active, not which ABI it exposes. The provider queries the exact ABI at startup with `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` and adapts as described above.
