# QEMU

**QEMU** is an **OS-sandbox** provider that runs code inside a virtual machine, using KVM when available or full CPU emulation otherwise. It works in constrained environments (e.g. unprivileged containers) and does not require host privileges.

A pre-built VM image with Python is downloaded and started. QEMU is launched with configured directories and network access. The VM boots, installs required components, starts the sandbox, and waits for commands.

This setup lets you restrict disk and network access (e.g. via iptables) even when the host is restricted, such as in an unprivileged container.

For more details, see the [QEMU documentation](https://www.qemu.org/).

## Using with Docker / Podman

The QEMU provider is compatible with Docker, Podman, and Kubernetes.

> Starting a virtual machine is much longer than a simple process.

## Image et version de Python

L’image par défaut est **Debian 12 (bookworm)** et fournit Python 3.11. Pour une **correspondance complète une image / une version Python à partir de 3.10**, utiliser les **images Ubuntu** (tableau ci‑dessous).

Définir l’URL de l’image choisie :

```bash
export PYSANDBOXES_QEMU_IMAGE_URL="<url complète de l'image>"
```

### Mapping : version Python → image (Ubuntu, 3.10 à 3.13)

Une seule source permet de couvrir 3.10, 3.11, 3.12 et 3.13 avec une image par version : **Ubuntu Cloud Images**.

| Python | Ubuntu        | Fichier (.img) | URL de base (release) |
|--------|---------------|----------------|------------------------|
| 3.10   | 22.04 LTS (Jammy)  | `ubuntu-22.04-server-cloudimg-<arch>.img` | `https://cloud-images.ubuntu.com/releases/22.04/release/` |
| 3.11   | 23.04 (Lunar)      | `ubuntu-23.04-server-cloudimg-<arch>.img` | `https://cloud-images.ubuntu.com/releases/23.04/release/` |
| 3.12   | 24.04 LTS (Noble)  | `ubuntu-24.04-server-cloudimg-<arch>.img` | `https://cloud-images.ubuntu.com/releases/24.04/release/` |
| 3.13   | 25.04 (Plucky)     | `ubuntu-25.04-server-cloudimg-<arch>.img` | `https://cloud-images.ubuntu.com/releases/25.04/release/` |

Remplacer `<arch>` par `amd64`, `arm64`, `ppc64el`, `riscv64` ou `s390x` selon la plateforme.

**Exemples d’URL complètes (amd64) :**

- Python 3.10 : `https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img`
- Python 3.11 : `https://cloud-images.ubuntu.com/releases/23.04/release/ubuntu-23.04-server-cloudimg-amd64.img`
- Python 3.12 : `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img`
- Python 3.13 : `https://cloud-images.ubuntu.com/releases/25.04/release/ubuntu-25.04-server-cloudimg-amd64.img`

**Alternative : Debian** (image par défaut du projet, 3.11 uniquement sans autre config) :

- Bookworm : `https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2`
- Pour 3.9 ou 3.13 avec Debian : Bullseye ou Trixie (voir [cloud.debian.org](https://cloud.debian.org/images/cloud/)).

## Configuration parameters

You can add QEMU-specific options in `.py-sandboxes`. Any line of the form `qemu.<option>=<value>` is passed to the QEMU process as `--<option>=<value>` when the VM is started.

### Memory (qemu.memory)

The VM needs enough RAM to boot the cloud image and run Python. **Default: 2048** (2 GiB). Lower values (e.g. 512) can cause out-of-memory during boot or when starting Python.

Examples in `.py-sandboxes`:

- `qemu.memory=2048` — 2 GiB (default, recommended)
- `qemu.memory=2G`  — same, QEMU accepts `G`/`M` suffix
- `qemu.memory=4096` — 4 GiB for heavier workloads
