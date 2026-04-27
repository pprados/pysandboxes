# QEMU VM provider

## Standard image directory

- **Default directory:** `$XDG_DATA_HOME/vm-images` (or `~/.local/share/vm-images` if `XDG_DATA_HOME` is unset).
- **Override:** set `PYSANDBOXES_VM_IMAGES_DIR` to an absolute path.
- **Default image name:** `pysandboxes-python-<major>.<minor>-<arch>.qcow2` (e.g. `pysandboxes-python-3.12-x86_64.qcow2`).
- Images in this directory can be shared with other tools; if a file already exists at the resolved path, the provider uses it without re-downloading.

**Auto-download:** If the image is missing, the provider (and `python -m pysandboxes.remote.qemu_fetch_image`) downloads it by default from a **standard QEMU/VM repository**: **Debian Cloud Images** (Bookworm generic qcow2 from cloud.debian.org). The image is saved under the default path above. Override with:
- `PYSANDBOXES_QEMU_IMAGE_URL` — full URL of the image (replaces default source).
- `PYSANDBOXES_QEMU_IMAGE_BASE_URL` — base URL; the default image filename is appended.

Supported architectures for the default source: amd64 (x86_64), arm64 (aarch64), ppc64el.

To see the resolved path or trigger a download: `python -m pysandboxes.remote.qemu_fetch_image`.

## Guest image contract

The guest VM image must:

1. **Python:** Provide Python with the same major.minor version as the host (e.g. 3.12).
2. **SSE server:** Run the pysandboxes SSE server (same as `main_sandbox`) listening on the port provided in the embedded config (same port number as on the host, chosen from available host ports).
3. **Config pipe:** On boot, mount the 9p share (tag `pysandbox_config`) at a known path (e.g. `/mnt/pysandbox_config`), then read the single config file (FIFO) from that directory. The host writes serialized `DaemonParameters` (including optional `netfilter_rules`) to that pipe.
4. **Network policy:** Before starting the SSE server, apply the injected iptables rules (e.g. `iptables-restore` with the `netfilter_rules` list from the config).
5. **QEMU Guest Agent (optional):** If present, the host may send `guest-shutdown` via QMP for clean shutdown; otherwise the host uses SIGTERM then SIGKILL on the QEMU process.

## 9p mount (guest side)

Example inside the guest:

```sh
mkdir -p /mnt/pysandbox_config
mount -t 9p -o trans=virtio pysandbox_config /mnt/pysandbox_config
# Then open the FIFO in that directory (single file) and read DaemonParameters + apply netfilter_rules.
```

## KVM vs TCG

If `/dev/kvm` is available and readable, the provider adds `-enable-kvm`. Otherwise QEMU runs in TCG (software emulation), which is slower but works without hardware virtualization.
