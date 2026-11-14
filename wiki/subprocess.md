# `subprocess` provider

`subprocess` runs the sandboxed code in a separate Python process of the same user, with no operating-system
boundary around it. It is the reference provider: the other providers extend the same daemon (`SubProcessDaemon`) and
add a launcher, a mount view or a kernel ruleset in front of the child.

It is the only provider that runs on every platform. A generated profile names it on Windows, on macOS when
`/usr/bin/sandbox-exec` is missing, and on a Linux whose kernel lacks Landlock (a warning says so). During learning,
`os-sandbox` is forced to `subprocess`.

## What it gives

- **Process separation.** The host application and the sandboxed code live in two processes. The host talks to the
  child over the local SSE transport and a crash of the child does not take the host down.
- **A watchdog.** The host restarts the child when it exits while calls are still accepted, with an exponential
  back-off. After too many restarts the sandbox stops restarting and fails closed: the call raises instead of ending
  the host application.
- **The Python layer, if `py-sandbox=true`.** Every guard (`python-import`, `python-api`, `eval-*`, files, environment,
  sockets) runs in the child, exactly as with any other provider.
- **The Unix-socket channel.** `remote-endpoint=auto` hands a listening descriptor down to the child (see
  [the channel](os-providers.md#how-the-host-reaches-the-sandbox-remote-endpoint)), so the channel needs no file rule
  and no network rule.
- **A clean shutdown.** The host asks the child to stop, then kills it if it does not answer in time.

## What it does not give

The child inherits the host's view: same user, same filesystem, same network, same kernel. Nothing is mounted,
hidden or filtered by the operating system. So:

| Control | With `subprocess` |
|---|---|
| `expose-ro=` / `expose-rw=` | Enforced by the Python guard only. Compiled code reads and writes anything the user can |
| `ignore=` | Python guard only |
| `net=` | Python socket guard only. Native code reaches any host, port and protocol |
| Compiled code, `ctypes`, direct syscalls | Not contained |
| Resource limits, seccomp | None |

With `py-sandbox=false` the provider enforces nothing at all. Use it for debugging, to tell whether a failure comes
from the Python layer or from an OS provider, not to run code you do not trust.

## When to choose it

- Your own scripts, where the risk is a mistake and not an attacker (see
  [Choosing by threat and cost](os-providers.md#choosing-by-threat-and-cost)).
- macOS without `sandbox-exec`, and Windows without `appcontainer`.
- A host where no kernel-backed provider is available and the Python guards are an accepted level of protection.
- Debugging, as the reference row: if a profile works under `subprocess` and fails under `bwrap`, `firejail` or
  `unshare`, the cause is the mount view or the filtering of that provider, not the profile.

For hostile native code, choose `bwrap` or `unshare`. See [Weaknesses](weaknesses.md) for what the Python layer does
not stop on its own.

## Example

```ini
py-sandbox=true
os-sandbox=subprocess
python-import=*
expose-ro=.
expose-rw=./tmp
```

The same file with `os-sandbox=bwrap` adds the kernel boundary; nothing else changes.

## Cost

About +0.10s of start-up over a bare interpreter and no measurable overhead on file operations, the same as `landlock`. See
[What each costs](os-providers.md#what-each-costs).

## Availability and tests

No binary, no kernel feature, no package extra: it is registered for every `sys.platform`. The unit and integration
suites run it on Linux, and the cross-OS workflow runs it on macOS and Windows.
