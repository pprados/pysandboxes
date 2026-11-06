# QEMU microvm

`os-sandbox=qemu-microvm` runs the sandbox in a Linux guest using QEMU's x86 `microvm` machine. The guest boots the
kernel and initrd matched to the root image, then applies the same file, network, and environment rules as the QEMU
provider. It is available on Linux x86_64 only.

## Choose it when

Use microvm when a separate guest kernel is part of the threat boundary and the smaller machine model fits the
workload. The host kernel does not run guest Python code. The Python guards remain enabled by default; QEMU does not
prevent a QEMU or guest-kernel escape.

KVM gives hardware-assisted virtualization. TCG emulates the CPU in the QEMU process and is useful for compatibility
checks, but does not provide the same hardware-virtualization isolation claim. The measured first SSE was 20.4 s with
KVM and 110.3 s with TCG on one host; expect large host-dependent differences. RSS measured about 703 MiB and 1.4 GiB,
respectively.

The guest uses QEMU's `max` CPU model, which exposes features supported by the selected accelerator. KVM exposes host
features; TCG emulates the features it supports. This lets modern binary wheels use their required CPU baseline.

## Requirements and boot files

Install `qemu-system-x86_64`, `qemu-utils`, `7zip`, and `genisoimage`. KVM is recommended; without usable `/dev/kvm`, set
`qemu.use_kvm=false` to select TCG explicitly. The provider fails before guest execution if its MMIO capacity probe,
boot artifacts, required mounts, network filter, or startup handshake fail.

The provider extracts a matched `vmlinuz-*` and `initrd.img-*` from the same Ubuntu cloud image used as the root disk.
It finds the partition by inspecting the image, then caches the pair beside that image. Install `7zip` for automatic
extraction. A read-only cache or missing extractor is an error; set both overrides to readable files when needed:

```text
qemu.microvm_kernel=/path/to/vmlinuz
qemu.microvm_initrd=/path/to/initrd.img
```

The guest has no RTC because the microvm machine's RTC IRQ conflicts with a virtio interrupt under TCG. Network time
sync updates the guest clock after startup. TLS access passed after sync; code that needs correct wall time before
network startup is not supported.

## MMIO capacity

The current microvm machine exposes eight virtio-mmio transports. One is used by the virtio-SCSI controller and one by
the network device, leaving at most six 9p shares. Configuration data is carried on the read-only NoCloud ISO. The
provider may merge nested mounts only when host path, read/write access, and security model remain equivalent.

`qemu.microvm_optional_paths=/etc/ssl,/etc/pki` marks exact guest mount paths as optional. The provider drops these
host shares in the listed order only when the profile exceeds the MMIO limit. The guest then uses its own existing
path; startup fails closed if that path is absent or another share overlaps it. Under capacity, the host shares stay
mounted. Use this only when the guest image's files are an acceptable substitute for the host files. A profile that
still exceeds capacity fails closed before user code runs.

`QEMU_MICROVM_OPTIONAL_PATHS` supplies default candidates when the profile has no `qemu.microvm_optional_paths` line.
It is useful for sample suites that share profiles across providers. Candidates that are not mounted by the current
profile are ignored; any candidate actually omitted still must exist in the guest image.

## Run it

```text
os-sandbox=qemu-microvm
qemu.use_kvm=true
```

The provider accepts the shared `qemu.*` settings documented in [QEMU](qemu.md). `qemu.show_boot_console=true` prints
the guest boot and bootstrap log. KVM and TCG test rows are separate; a TCG result is not KVM evidence.

## Containers

Build the image from the project root:

```bash
make build-image-qemu-microvm
```

It is published as `python-sb-qemu-microvm`, based on the QEMU image with the matched direct-boot artifacts prepared.
To pass KVM into Docker when the host provides it:

```bash
docker run --rm --device /dev/kvm --group-add "$(stat -c %g /dev/kvm)" \
  -v "$(pwd)":/app -w /app python-sb-qemu-microvm:latest \
  sh -c 'OS_SANDBOX=qemu-microvm python-sb my_script.py'
```

Podman uses the same image and device options. Without `/dev/kvm`, QEMU uses TCG and startup is much slower. Kubernetes
needs the same image and, for acceleration, a node policy that permits the `/dev/kvm` device. The image smoke test
boots the guest behind a network rule when KVM is available.

## Limits

- Linux x86_64 only.
- Up to eight virtio-mmio transports, including the SCSI controller and network device.
- TCG is much slower and does not carry the KVM isolation claim.
- The initial guest clock is not reliable until network time sync completes.
- A guest kernel or QEMU vulnerability can still affect the host; keep both updated.
- The VM adds startup and memory cost. Keep a sandbox alive across calls when practical.

See [OS provider comparison](os-providers.md), [weaknesses](weaknesses.md), and [QEMU](qemu.md).
