<!-- Copyright (c) 2026, Carbon-It, Philippe Prados (pprados) -->
<!-- License: Apache V2 -->

# Native code and OS-boundary assessment

## Scope and method

This assessment covers Linux OS-provider boundaries, QEMU host shares, and the feasibility of native replacements for Python API guards. Its probes date from 2026-10-16. On 2026-11-13, at commit `2601d77b` (release 0.12.0), the findings were re-checked by reading the provider code, and a section was added for the providers the probes did not cover. No probe was re-run on that date. Prototype descriptions are not evidence of current enforcement.

Evidence labels used below:

- **Reproduced**: exercised against the current implementation in an isolated probe.
- **Code-established**: the current implementation directly exhibits the behavior; no end-to-end guest or kernel probe was run.
- **Conditional**: the behavior depends on a stated configuration, platform, or capability.

The Python patching and `eval-*` layers have separate assessments: [Python layer](audit-python-security.md) and [`eval-*`](audit-eval-security.md). Provider setup and prerequisites are described in [OS providers](os-providers.md).

## Findings

### QEMU `expose-ro` is enforced by a read-only 9p export

The audit first reproduced a native guest write to a host sentinel through an `expose-ro` share with `py-sandbox=false`. The QEMU command omitted the export's `readonly=on` option, and the guest mount had no `ro` option. This is fixed by passing `readonly=on` to each 9p export created for an `FSExposeRule(write=False)`. The regression test boots a local Ubuntu cloud image under QEMU TCG and confirms native `libc.open(..., O_WRONLY | O_TRUNC)` is refused and the host sentinel is unchanged: [`test_qemu_readonly_share.py`](../tests/integration_tests/test_qemu_readonly_share.py).

The enforcing control is QEMU's host-side export option, so a guest cannot restore write access by remounting its view. QEMU documents 9p exports as read-write by default unless `readonly=on` is set ([QEMU manual](https://www.qemu.org/docs/master/system/qemu-manpage.html)). The integration test is the current evidence for this exact filesystem-share behavior; it does not establish protection against a QEMU hypervisor escape.

This result is specific to QEMU 9p shares. It does not establish that every provider's read-only rules behave identically.

### Landlock denies native TCP by default; UDP remains outside its controls

The audit reproduced a native loopback TCP `connect()` on ABI 8 when no socket rules were configured. The provider now always marks Landlock TCP bind/connect rights as handled and passes an empty allowlist when no `net=` rules exist. A focused integration test confirms a native connection to a reachable host listener is refused in both `python-sb` and daemon modes. On kernels below ABI 4, the provider reports unavailable and refuses to start rather than running without this boundary. Landlock cannot filter UDP at any supported ABI. See [`landlock_daemon.py`](../pysandboxes/remote/landlock_daemon.py) and [Landlock limits](landlock.md#limits).

### Landlock's `/dev` access is broader than regular-file rules

**Evidence: reproduced with a limited operation.**

Under the tested Landlock profile, native code successfully opened `/dev/full` for writing. The probe did not write to it and did not establish access to a high-impact device: `/dev/kvm`, `/dev/dri`, and `/dev/fuse` were unavailable in the test environment. This establishes that an allowed device-node open can remain possible; it does not establish a privilege escalation or arbitrary device access. Device availability and host permissions determine practical impact.

### Some mount failures are logged but do not abort startup

**QEMU: fixed, code-established at `2601d77b`.** On 2026-10-16 the guest bootstrap ran each 9p mount and ignore overlay with `|| true` and continued, so a failed share could leave a requested path unmounted. The bootstrap now calls `_pysb_fatal` when a required 9p share cannot be mounted (`cannot mount required 9p share`), when the ignore placeholder cannot be protected, and when an ignore overlay cannot be mounted (`cannot mount ignore overlay`). `_pysb_fatal` logs to the run directory's stderr file, powers the guest off and exits 1, so no user code starts. The `qemu-microvm` provider shares this setup code. [Weaknesses](weaknesses.md#os-provider-limitations) cites fault-injection tests for it; they were not re-run for this page. An ignore path absent from the guest is skipped silently (`[ -e "$ign_path" ] || continue`), which is correct for a path that does not exist. See [`qemu_setup.py`](../pysandboxes/remote/qemu_setup.py).

**Unshare ignore overlays: reproduced for a failed overlay mount.** The ignore-overlay loop catches a mount error, logs a warning, and continues. This finding is limited to that path: user-defined bind mounts use a separate setup path whose failures are propagated. A failed ignore overlay can leave the ignored path visible; verify effective mounts when relying on an ignore rule. See [`unshare_sse_daemon.py`](../pysandboxes/remote/unshare_sse_daemon.py) and [`unshare_setup.py`](../pysandboxes/remote/unshare_setup.py).

These findings do not mean every mount fails. They mean startup success alone does not prove that every requested mount policy was applied.

## Coverage of the other providers

The 2026-10-16 probes covered `landlock`, `unshare` and the QEMU 9p shares. The registry at `2601d77b` lists twelve public providers: `none`, `subprocess`, `appcontainer` (Windows), `landlock`, `bwrap`, `firejail`, `unshare`, `qemu`, `qemu-microvm` (Linux x86_64), `gvisor`, `smolvm` and `sandbox-exec` (macOS). No probe was run for this section. Every row below is **documented by the project** in [OS providers](os-providers.md) and the provider pages, and is not re-established here. Read it as the claim to test, not as a result.

| Provider | Boundary | What the documentation says native code cannot do | What it says remains open |
|---|---|---|---|
| `none`, `subprocess` | None | Nothing | Everything; `none` also leaves the Python guards inactive. |
| `landlock` | Kernel ruleset on the process itself | Open unlisted paths; TCP connect or bind outside `net=` rules (ABI 4 or later) | UDP; hiding a path (`ignore=`); named Unix sockets under `/run` such as the D-Bus session bus and `docker.sock`; opening an allowed device node. |
| `bwrap`, `unshare` | Mount and network namespaces on the host kernel | See paths that are not exposed; reach hosts outside `net=` rules | A kernel exploit reaches the host; `unshare` continues after a failed ignore overlay (reproduced above). |
| `firejail` | Namespaces, setuid-root binary, seccomp, resource limits | Create a Unix socket; see blacklisted paths | Needs root for `net-resolve=runtime`; not usable in a container. |
| `gvisor` | A user-space kernel (Sentry) | Reach host Unix sockets (`--host-uds=none`); most host system calls | Slower on system calls; no Unix-socket channel to the host. |
| `smolvm`, `qemu`, `qemu-microvm` | A VM with its own kernel | Reach the host kernel; see unexposed files; write a read-only share | `smolvm`: DNS for subdomains of allowed hosts, and a TCP rule opens every port of its address. `qemu` and `qemu-microvm` under TCG carry no isolation claim. `qemu-microvm` has at most eight virtio-mmio transports. |
| `sandbox-exec` | A Seatbelt profile (deprecated by Apple) | Reach ports outside the rules | No host filter; an allowed UDP 53 grants the system resolver socket. |
| `appcontainer` | An AppContainer token | Reach files outside the rules; reach the network without an `ALLOW` rule | No host, port or protocol filter; loopback blocked even when a rule allows it. |

The DNS channel is a separate, code-established residual for every provider that has its own network namespace; see [Weaknesses](weaknesses.md#os-provider-limitations) and [DNS](dns.md).

## Native guard feasibility

The current production boundary is implemented by Python guards plus OS-provider mechanisms; this assessment found no production native extension that replaces the Python guard tables. A native wrapper around selected Python callables would not enforce filesystem, network, process, or device policy. It also would not remove the Python object-model limitations documented in the refreshed [Python-layer assessment](audit-python-security.md), including `object.__subclasses__` traversal, an already-loaded pickle implementation (`_pickle` keeps its own references), and frame/global introspection.

Those are limitations of same-process Python mediation. They are not evidence that a kernel-backed provider is bypassed. Native code and direct system calls must be constrained by a correctly configured OS boundary.

## Decision

Do not treat a native wrapper around selected Python callables as the security boundary. Keep Python guards as policy enforcement for supported APIs, and select an OS provider according to the attacker capabilities and resources in scope. QEMU `expose-ro` and Landlock's default TCP denial now have regression coverage; Landlock UDP and device-node exposure remain outside its network/filesystem allowlist controls.

`none` and `subprocess` do not supply a kernel-enforced OS boundary. For the limitations of same-process guards and remote result handling, see [Weaknesses](weaknesses.md), [Python layer](audit-python-security.md), and [`eval-*`](audit-eval-security.md).

## References

- [Python-layer assessment](audit-python-security.md)
- [`eval-*` assessment](audit-eval-security.md)
- [Weaknesses](weaknesses.md)
- [OS providers](os-providers.md)
- [QEMU 9p mount construction](../pysandboxes/remote/qemu_sse_daemon.py)
- [QEMU guest setup](../pysandboxes/remote/qemu_setup.py)
- [Landlock provider](../pysandboxes/remote/landlock_daemon.py)
