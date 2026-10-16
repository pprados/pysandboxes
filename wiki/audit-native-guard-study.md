<!-- Copyright (c) 2026, Carbon-It, Philippe Prados (pprados) -->
<!-- License: Apache V2 -->

# Native code and OS-boundary assessment

## Scope and method

This assessment covers the boundary that remains relevant when sandboxed work can use native code: the Linux OS providers, QEMU's host shares, and the feasibility of a native replacement for Python API guards. It was checked against the current provider implementation and isolated probes. It does not treat earlier descriptions of a prototype as evidence for current enforcement.

Evidence labels used below:

- **Reproduced**: exercised against the current implementation in an isolated probe.
- **Code-established**: the current implementation directly exhibits the behavior; no end-to-end guest or kernel probe was run.
- **Conditional**: the behavior depends on a stated configuration, platform, or capability.

The Python patching and `eval-*` layers have separate assessments: [Python layer](audit-python-security.md) and [`eval-*`](audit-eval-security.md). Provider setup and prerequisites are described in [OS providers](os-providers.md).

## Findings

### QEMU `expose-ro` shares are writable by guest code

**Severity: high when the profile relies on `expose-ro` to protect host files. Evidence: reproduced.**

With `py-sandbox=false`, `os-sandbox=qemu`, and a host directory exposed using `expose-ro`, native guest code opened a host sentinel through the 9p share with `libc.open(..., O_WRONLY | O_TRUNC)`, wrote new contents, and exited successfully. The host file changed. The probe ran against the local Ubuntu cloud image under QEMU TCG; it did not depend on KVM.

The code path explains the result: [`_file_rules_mounts`](../pysandboxes/remote/qemu_sse_daemon.py) keeps the host path and mount tag but does not carry `FSExposeRule.write` into the QEMU share options. The guest bootstrap mounts each 9p tag without a read-only option ([`qemu_setup.py`](../pysandboxes/remote/qemu_setup.py)). QEMU documents that a 9p export is read-write by default unless `readonly=on` is set ([QEMU manual](https://www.qemu.org/docs/master/system/qemu-manpage.html)). Therefore the Python file guard cannot make this share read-only when it is disabled or bypassed by native guest code.

Treat QEMU `expose-ro` as writable until the provider passes an end-to-end regression probe that writes through a guest native syscall and confirms the host file remains unchanged. This finding concerns that QEMU mount mode; it is not evidence that every provider's read-only rules fail.

### Landlock does not restrict networking without socket rules

**Evidence: reproduced; conditional on omitting `net=` rules or lacking Landlock network ABI support.**

On the tested Linux kernel (Landlock ABI 8), a native loopback `connect()` succeeded under Landlock when no socket rules were configured. The current activation code passes `net_ports=None` when `all_rules.socket_rules` is empty. Network restriction is therefore not implicit merely because filesystem Landlock is active. On kernels below ABI 4, Landlock cannot apply its TCP bind/connect restrictions at all; check provider availability and kernel support before relying on `net=` enforcement. See [`landlock_daemon.py`](../pysandboxes/remote/landlock_daemon.py) and [Landlock limits](landlock.md#limits).

### Landlock's `/dev` access is broader than regular-file rules

**Evidence: reproduced with a limited operation.**

Under the tested Landlock profile, native code successfully opened `/dev/full` for writing. The probe did not write to it and did not establish access to a high-impact device: `/dev/kvm`, `/dev/dri`, and `/dev/fuse` were unavailable in the test environment. This establishes that an allowed device-node open can remain possible; it does not establish a privilege escalation or arbitrary device access. Device availability and host permissions determine practical impact.

### Some mount failures are logged but do not abort startup

**QEMU: code-established.** The guest bootstrap runs each configured 9p mount and ignore overlay with `|| true`, then continues. A failed share can consequently leave a requested path unmounted without failing bootstrap. This was not separately induced in a guest fault-injection probe. See [`qemu_setup.py`](../pysandboxes/remote/qemu_setup.py).

**Unshare ignore overlays: reproduced for a failed overlay mount.** The ignore-overlay loop catches a mount error, logs a warning, and continues. This finding is limited to that path: user-defined bind mounts use a separate setup path whose failures are propagated. A failed ignore overlay can leave the ignored path visible; verify effective mounts when relying on an ignore rule. See [`unshare_sse_daemon.py`](../pysandboxes/remote/unshare_sse_daemon.py) and [`unshare_setup.py`](../pysandboxes/remote/unshare_setup.py).

These findings do not mean every mount fails. They mean startup success alone does not prove that every requested mount policy was applied.

## Native guard feasibility

The current production boundary is implemented by Python guards plus OS-provider mechanisms; this assessment found no production native extension that replaces the Python guard tables. A native wrapper around selected Python callables would not enforce filesystem, network, process, or device policy. It also would not remove the Python object-model limitations documented in the refreshed [Python-layer assessment](audit-python-security.md), including immutable `object.__subclasses__`, an already-loaded pickle implementation, frame/global introspection, and immutable `pickle.Unpickler.load`.

Those are limitations of same-process Python mediation. They are not evidence that a kernel-backed provider is bypassed. Native code and direct system calls must be constrained by a correctly configured OS boundary.

## Decision

Do not treat a native wrapper around selected Python callables as the security boundary. Keep Python guards as policy enforcement for supported APIs, and select an OS provider according to the attacker capabilities and resources in scope. Current QEMU read-only shares need correction and end-to-end coverage before they can be relied upon. Landlock requires explicit, supported network rules for TCP filtering, and device-node exposure should be considered in the deployment threat model.

`none` and `subprocess` do not supply a kernel-enforced OS boundary. For the limitations of same-process guards and remote result handling, see [Weaknesses](weaknesses.md), [Python layer](audit-python-security.md), and [`eval-*`](audit-eval-security.md).

## References

- [Python-layer assessment](audit-python-security.md)
- [`eval-*` assessment](audit-eval-security.md)
- [Weaknesses](weaknesses.md)
- [OS providers](os-providers.md)
- [QEMU 9p mount construction](../pysandboxes/remote/qemu_sse_daemon.py)
- [QEMU guest setup](../pysandboxes/remote/qemu_setup.py)
- [Landlock provider](../pysandboxes/remote/landlock_daemon.py)
