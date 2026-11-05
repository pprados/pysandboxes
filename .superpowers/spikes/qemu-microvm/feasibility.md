# QEMU microvm feasibility

Date: 2026-11-05

## Decision

`os-sandbox=qemu-microvm` is technically feasible on Linux x86_64. Expose it as a distinct provider, but share the
existing QEMU daemon, transport, staging, netfilter, console, and cleanup implementation. Do not copy the current
daemon.

Use the strict `microvm,acpi=off,pcie=off` model with virtio-mmio. A PCIe-enabled microvm would preserve more of the
current command, but it would retain the PCI surface that motivates this provider. Keep `os-sandbox=qemu` for broad
architecture and device compatibility.

The provider is not ready to ship from this spike. Production integration still needs a reproducible kernel/initrd
artifact pipeline, repeatable KVM benchmarks, fail-closed guest mounts, and the full security suites.

## Evidence

Host: QEMU 10.2.1, Linux x86_64. The managed filesystem sandbox hides `/dev/kvm`; approved unsandboxed execution
shows `/dev/kvm` as `root:kvm 0660`, the user in group `kvm`, and a successful QEMU/KVM machine start.

| Question | Result | Evidence |
|---|---|---|
| Does the machine exist? | Yes, x86 only on this installation. | `qemu-system-x86_64 -machine help`; no `microvm` in the aarch64 list. |
| Can the current QEMU command be reused unchanged? | No. | `virtio-net-pci`, `virtio-serial-pci`, `-drive if=virtio`, and `-virtfs` fail with `No 'PCI' bus found`. |
| Do MMIO replacements exist? | Yes. | Automated probes start `virtio-net-device`, `virtio-serial-device`, `virtio-blk-device`, and `virtio-9p-device`. |
| Can the existing cloud disk boot through firmware? | No. | QEMU documentation requires host-side kernel boot for virtio-mmio; a disk-only probe reports `No bootable device`. |
| Does direct kernel boot work? | Yes. | Kernel reaches the virtio root disk, mounts `vda1`, and starts systemd. |
| Do cloud-init, network, and 9p work together? | Yes under TCG and KVM. | Tests obtain `10.0.2.x`, mount a read-only 9p sentinel, and emit `PYSANDBOXES_MICROVM_MMIO_OK`. |
| Are MMIO devices unlimited? | No. | The local QEMU accepts 24 transports and rejects the next device as full. Runtime preflight must not assume one fixed count across QEMU versions. |
| Is KVM usable? | Yes. | Minimal KVM start succeeds; the complete probe succeeds in 43.22 s while running beside another KVM probe. |

Probe: `.superpowers/spikes/qemu-microvm/test_qemu_microvm_probe.py`.

## Required design

The launch remains a VM launcher:

1. Resolve the current cloud image.
2. Resolve a version-matched kernel and initrd outside the disk. Cache and verify them with the image.
3. Build the existing NoCloud data, but attach it through `virtio-blk-device`.
4. Attach root disk, user-mode network, and each 9p export through virtio-mmio devices.
5. Direct-boot with `console=ttyS0 root=/dev/vda1 ro reboot=t`, explicit serial, and `-no-reboot`.
6. Run the existing bootstrap, iptables filter, Python guards, and SSE server.
7. Fail before launch if required artifacts are absent or the required MMIO device count exceeds the machine capacity.

Kernel/initrd extraction is the largest packaging decision. The spike extracted the matching files from the cloud
image using Ubuntu's `7zip` package. Production code must discover the boot partition and matching pair, verify the
pair, cache atomically, and test every supported image. Fixed partition numbers are unacceptable.

## Rule disposition

| Rule | Intended enforcement | Status |
|---|---|---|
| `expose-ro` | Read-only virtio-9p export and guest mount | Transport proved; native write refusal still needs integration coverage. |
| `expose-rw` | Writable virtio-9p export and guest mount | Transport proved; host round-trip still needs integration coverage. |
| outside paths | Separate guest kernel and only explicit 9p exports | Same isolation model as QEMU; shared OS-only file suite required. |
| `ignore=` | Guest bind-mask after 9p mounts | Shared QEMU bootstrap currently tolerates mount errors. Must become fail-closed for both providers. |
| `net=` | Guest iptables over QEMU user network | DHCP proved. OS-only deny/allow test with Python guards disabled remains mandatory. |
| env rules | Clean guest process environment | Reuse current QEMU path; shared usage and partial-mode suites must prove it. |

## Advantages

- Smaller emulated platform and device surface than the PC machine.
- Direct kernel boot avoids firmware and bootloader discovery.
- Full VM boundary remains stronger than namespace-only providers against guest kernel attacks.
- Unprivileged TCG remains possible inside Docker, Podman, and Kubernetes.
- Existing QEMU SSE, rules, staging, console, and cleanup code is reusable.

## Limits and risks

- Linux x86_64 only. QEMU `microvm` is not the aarch64 `virt` machine.
- A matched kernel/initrd becomes a third artifact contract beside the root image and NoCloud disk.
- Finite MMIO slots bound the number of independent 9p exports. The provider must fail clearly, never drop a rule.
- TCG is explicitly outside QEMU's hardware-virtualization security guarantee and was slow: 69.37 s in the latest
  complete probe.
- KVM reduced the same complete probe to 43.22 s despite a concurrent KVM boot. This is feasibility evidence, not a
  controlled benchmark; production measurements still need isolated repeated runs and RSS collection.
- No hotplug; no live migration across QEMU versions.
- The host QEMU process still needs its own confinement and resource limits; a smaller guest machine is not a
  hypervisor-escape defense.
- DNS exfiltration, result-channel trust, 9p exposure, and current QEMU mount-error weaknesses remain shared risks.
- Context7 could not be used because its credential refresh required a rejected external write. Evidence instead
  uses QEMU 10.2.1 runtime introspection, packaged QEMU documentation, repository code, and executable probes.

## Ship/no-ship gates

Ship only after KVM and TCG pass provider-specific, shared guard/usage, OS-only file/network, container, sample, and
cleanup suites. Do not ship if boot artifacts cannot be reproduced for Python 3.11 through 3.14, if a file rule can
be silently omitted through MMIO exhaustion, or if any guest mount failure continues execution unrestricted.
