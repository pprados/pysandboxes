# macOS `sandbox-exec` provider

`sandbox-exec` starts the existing PySandboxes SSE daemon under an Apple Seatbelt profile generated for each run. It
uses `/usr/bin/sandbox-exec`; the command is deprecated by Apple and may be removed in a future macOS release. The
provider is opt-in, macOS-only, and is not the default. On macOS, generated profiles continue to use `subprocess`
unless `os-sandbox=sandbox-exec` is selected explicitly.

This is an OS access-control layer, but it is not one of the Linux kernel providers and it does not create a separate
filesystem or network namespace. It must not be treated as a VM boundary.

## What it enforces

- Default-deny file access, with runtime paths needed by Python and the daemon, configured `expose-ro` / `expose-rw`
  paths, and deny rules for `ignore=` patterns.
- Default-deny network access, with supported TCP/UDP direction and port grants. Localhost rules remain scoped to
  localhost. Port 0 (the request for an automatically assigned port) cannot be expressed and stays denied; a warning
  is logged when such a rule is present.
- The Seatbelt profile never exists as a file. It reaches `sandbox-exec -f` through a named pipe (mode `0600`) in the
  private daemon run directory, is written once, and the pipe is removed as soon as it has been read. Nobody can read
  the profile back or replace it before it is applied. The residual boundary is the same one as the other providers:
  a process of the same user, or root.
- `TMPDIR` points to a private scratch directory, the only writable temporary location. It is removed with the daemon.
- No root privilege is needed: the provider runs as an ordinary user.
- `ignore=` is a deny rule placed after the allow rules (the last matching rule wins), so a read or write of an
  ignored path raises `PermissionError`, in the sandboxed process and in its children.

## Network limitations

Seatbelt's SBPL `remote` address accepts `*` or `localhost`, not a configured remote IP or hostname. A rule such as
`net=ALLOW|TCP|203.0.113.7|443|OUT` therefore becomes a grant for TCP port 443 to any remote host in the Seatbelt
layer. The provider logs a warning. With `py-sandbox=true`, the Python socket guard still checks the configured host;
with `py-sandbox=false`, native code can use any remote host on that protocol and port.

DNS works differently from Linux. On macOS, `getaddrinfo` does not send UDP datagrams to port 53: it talks to the
system resolver through the Unix socket `/var/run/mDNSResponder`. A `net=ALLOW|UDP|*|53|OUT` rule therefore becomes
a grant on that socket, and no UDP rule at all. The provider logs a warning. Names then resolve through the system
resolver, whatever its upstream server, so the DNS server of the provider cannot be pinned to one IP. A client that
sends its own DNS datagrams (a DNS library, `dig`) gets no answer. Other UDP rules (for example port 123) stay
plain port rules.

Seatbelt's allow/deny rules do not support the same address exceptions as the Python socket guard. The provider keeps
overlapping denies closed by omitting the conflicting broad allow. Review the warnings whenever a profile grants
remote access or DNS.

## Example

```ini
py-sandbox=true
os-sandbox=sandbox-exec
python-import=*
expose-ro=.
expose-rw=./tmp
net=ALLOW|TCP|github.com|443|OUT
```

The Python guard resolves and checks the configured hostname. Seatbelt itself only restricts the TCP port; compiled
or native code can reach other hosts on port 443. For workloads that need OS-enforced remote host filtering, choose a
provider that can express it on the target platform.

## Availability and tests

The provider requires Apple's `/usr/bin/sandbox-exec`. It needs no package extra and has no Docker/Podman image:
Seatbelt policy is a Darwin facility and cannot run in the project's Linux provider images. The cross-OS workflow
runs the provider suites on macOS, including direct Seatbelt file and socket checks. Windows and Linux do not import
the provider module unless it is explicitly selected (and the platform check rejects that selection).
