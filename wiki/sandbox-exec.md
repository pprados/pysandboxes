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
- The Seatbelt profile is created with mode `0600` in the private daemon run directory. `TMPDIR` is set to that same
  directory so Python temporary files remain inside the granted writable path. The inherited subprocess cleanup
  removes the profile and run directory after shutdown.

## Network limitations

Seatbelt's SBPL `remote` address accepts `*` or `localhost`, not a configured remote IP or hostname. A rule such as
`net=ALLOW|TCP|203.0.113.7|443|OUT` therefore becomes a grant for TCP port 443 to any remote host in the Seatbelt
layer. The provider logs a warning. With `py-sandbox=true`, the Python socket guard still checks the configured host;
with `py-sandbox=false`, native code can use any remote host on that protocol and port.

DNS is another limitation. To receive DNS replies under the deny-default profile, the provider adds
`(allow network-inbound (local udp))` when UDP port 53 is granted outbound. That permission is not restricted to a
source or destination port. The provider logs a warning; when `py-sandbox=false`, native code can receive local UDP
traffic more broadly than the profile's `net=` rule suggests.

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
