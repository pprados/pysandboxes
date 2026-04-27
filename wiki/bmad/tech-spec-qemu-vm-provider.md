---
title: 'QEMU VM provider for pysandboxes'
slug: 'qemu-vm-provider'
created: '2025-03-14'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.10+', 'QEMU system emulation', 'SSE over HTTP', 'QEMU Guest Agent', 'XDG Base Dir for vm-images']
files_to_modify: ['pysandboxes/_os_sandbox.py', 'pysandboxes/remote/main_sandbox.py', 'pysandboxes/python_sb.py', 'pysandboxes/remote/vm_sse_daemon.py (new)', 'pysandboxes/remote/qemu_sse_daemon.py (new)', 'pysandboxes/remote/qemu_image.py or equivalent (new)', 'tests/integration_tests/test_usage_with_providers.py', 'tests/containers/test_containers.py']
code_patterns: ['BaseSubProcessDaemon extension with __slots__', 'subprocess_cmd(all_rules, envs, pipe_path, temp) -> (Args, Environ)', '_re_start_cmd override to avoid appending --_named-pipe for QEMU', 'launch_sandbox: creates FIFO, starts process, on_launched(pid), then writes process_config to pipe', 'parse_rules(rules, errors) -> (ImmutableDict params, ConfigLines rest) for qemu.*']
test_patterns: ['pytest, conftest fixtures, pytest.mark.parametrize', 'unit tests for KVM detection, image path resolution, QEMU cmd building', 'MagicMock/AsyncMock for deps', 'integration tests optional with env/requires marker']
---

# Tech-Spec: QEMU VM provider for pysandboxes

**Created:** 2025-03-14

## Overview

### Problem Statement

The framework needs stronger isolation than OS namespaces alone. We want to run Python code inside a full VM (QEMU) so that the security boundary is the hypervisor, while still supporting **unprivileged containers** (no `--privileged`, no `NET_ADMIN`, no mandatory `/dev/kvm`). Network policy must be enforced **inside the VM** via iptables so the host/container does not need network privileges. A **standard image** (Python version matching the host) must be **downloadable** and stored in a **standard directory** so the same image can be **reused** by other tools or already be present on disk for another need.

### Solution

Add a new provider **`qemu`** that:

- Introduces an abstract **`VMSSEDaemon`** (inheriting from `BaseSubProcessDaemon`) and a concrete **`QemuSSEDaemon`**.
- Uses QEMU with **`-net user`** and **hostfwd** for the SSE port (no TAP/bridge on host).
- Auto-detects **KVM** vs **TCG**: use `-enable-kvm` only when `/dev/kvm` is available and usable.
- Injects configuration and iptables rules into the guest via a **named pipe** (host creates pipe, exposes it to the guest via virtio-9p; guest reads config and applies iptables before starting the SSE server).
- Uses **QEMU Guest Agent (QGA)** for clean shutdown via QMP `guest-shutdown`.
- Uses a **standard image** (minimal Linux + Python **matching the host Python version**) that is **downloaded** on first use or via a dedicated command; image is placed in a **standard directory** so it can be **reused by other tools** (or an image already on disk for another need can be used).
- **Standard directory**: `$XDG_DATA_HOME/vm-images` (configurable via `PYSANDBOXES_VM_IMAGES_DIR` or equivalent), compatible with common VM/container image layouts so the same image may be shared across solutions.

### Scope

**In Scope:**

- Abstract class `VMSSEDaemon` and concrete `QemuSSEDaemon`.
- Registration of `qemu` in `providers_factory` and guard_provider / main_sandbox support.
- **Standard image**: Pre-built image (minimal Linux + Python) with Python version **equal to the host** (e.g. from `sys.version_info` or project `requires-python`); image is **downloaded** to the standard directory on first use (or via a dedicated CLI/entry point, e.g. `python -m pysandboxes.remote.qemu_fetch_image`). Default image name/identifier includes Python version (e.g. `pysandboxes-python-3.12-<arch>.qcow2`) so the same file can be reused by other tools or already present on disk.
- **Standard directory**: `$XDG_DATA_HOME/vm-images` (or configurable); if an image already exists at the resolved path (e.g. placed by another solution), the provider **uses it** without re-downloading. Document this layout for interoperability.
- **Launch**: Provider launches the (default or user-specified) image via QEMU; when no custom image is configured, use the standard downloaded image for the current Python version.
- QEMU command-line construction: image path from standard dir or `qemu.image` param, `-net user,hostfwd=tcp:HOST_PORT-:GUEST_PORT`, virtio-serial for QGA, virtio-9p to expose host config directory (containing the named pipe).
- Named-pipe config injection: host creates pipe in temp dir, mounts that dir in guest via 9p; guest process receives `--_config-pipe <guest_path>` and reads `DaemonParameters` + iptables rules (same format as unshare/firejail); guest applies `iptables-restore` then starts SSE server.
- KVM/TCG auto-detection; image directory resolution from env/config; `parse_rules` for `qemu.*` (e.g. `qemu.image`, `qemu.memory`, `qemu.use_kvm`).
- Lifecycle: `_start` (ensure image present, create pipe, start QEMU, wait for forwarded port), `_stop`/`_shutdown` (prefer QGA `guest-shutdown`, else SIGTERM/SIGKILL on QEMU process).
- Reuse `rule_to_netfilter` for socket rules; inject resulting list in the config stream to the guest.

**Out of Scope:**

- Proxmox or qemu-server dependency; only QEMU CLI (or equivalent).
- TAP/bridge or host iptables; all network policy inside the VM.
- Building the standard image from scratch in this repo (image is pre-built and distributed; download + optional checksum verification only).

## Context for Development

### Codebase Patterns

- **Provider registration**: Add to `providers_factory` in `_os_sandbox.py`; guard_provider validates `os-sandbox=qemu`; provider-specific params via `parse_rules` (e.g. `qemu.*` → `os_sandbox_params`).
- **Subprocess vs QEMU**: For `qemu`, the “subprocess” is the QEMU binary; the host does not run `python -m main_sandbox`. The guest runs the equivalent of main_sandbox (SSE server) after reading config from the pipe. Launch path in `python_sb.py` must support a provider that returns a QEMU command (and optionally different handling for pipe/process).
- **Config injection**: Unshare uses `UnshareSetupConfig` (JSON) and a named pipe; firejail uses FIFOs for netfilter. For QEMU, same conceptual flow: host writes structured config (params + netfilter rules) to a pipe; guest reads and applies. Pipe is exposed to guest via 9p mount of the host temp dir.
- **Netfilter**: Use `netfilter.rule_to_netfilter(socket_rules, dns_servers, is_ipv6)` to produce iptables list; inject that list in the config payload for the guest; guest runs `iptables-restore` before starting the SSE server.
- **main_sandbox.py**: Line 102 asserts `os_sandbox in ("subprocess", "firejail", "unshare", "landlock", "bwrap")`. Add `"qemu"` so the guest (running main_sandbox inside the VM) is allowed.
- **QEMU launch**: For QEMU, `subprocess_cmd` returns the full QEMU command; `_re_start_cmd` must not append `["--_named-pipe", str(pipe_path)]` to args (override in QemuSSEDaemon). In `python_sb.py`, when `os_sandbox == "qemu"` use only `cmd` (no `cmd + python_cmd`).

### Files to Reference

| File | Purpose |
|------|---------|
| `pysandboxes/_os_sandbox.py` | `providers_factory`, `async_start_daemon` |
| `pysandboxes/remote/sse_client_subprocess_daemon.py` | `BaseSubProcessDaemon`, `subprocess_cmd`, `DaemonParameters`, `launch_sandbox` flow |
| `pysandboxes/remote/sse_unshare_daemon.py` | `UnshareSSEDaemon`, named pipe, `get_launch_extras`, netfilter injection |
| `pysandboxes/remote/unshare_setup.py` | `UnshareSetupConfig`, reading config in “guest” (namespace) |
| `pysandboxes/python_sb.py` | Entry: `subprocess_cmd`, `get_launch_extras`, `launch_sandbox` — adapt for QEMU (QEMU process, not Python) |
| `pysandboxes/netfilter.py` | `rule_to_netfilter` |
| `pysandboxes/guard_provider.py` | Provider name validation |
| `pysandboxes/remote/main_sandbox.py` | Allowed `os_sandbox` list (add `qemu`) |
| `wiki/bmad/planning-artifacts/research/technical-qemu-vm-provider-sandbox-research-2025-03-13.md` | Full research and architecture |

### Technical Decisions

- **VMSSEDaemon** in same package as `QemuSSEDaemon` (e.g. `remote/vm_sse_daemon.py` for abstract base, `remote/qemu_sse_daemon.py` for QEMU implementation), or single module with both: prefer two modules for clarity and future VM providers.
- **Guest config format**: Reuse a JSON-like structure compatible with existing `DaemonParameters` and a `netfilter_rules` list (same as unshare) so guest script can share parsing patterns.
- **Standard image directory**: Default `$XDG_DATA_HOME/vm-images` (XDG-compliant, shared-friendly); override with `PYSANDBOXES_VM_IMAGES_DIR`. Same layout allows other solutions to use the same directory; if an image is already present at the resolved path, use it (no re-download).
- **Standard image**: One default image per (Python major.minor, arch): e.g. `pysandboxes-python-3.12-x86_64.qcow2`. Python version in image must match host (from `sys.version_info`). Image is downloaded on first use or via a dedicated fetch command; checksum verification optional. If user sets `qemu.image` to an existing path, that path is used as-is.
- **QGA**: Add virtio-serial device for QGA in QEMU command; use QMP socket (or monitor) to send `guest-shutdown` on _stop/_shutdown when available; fallback to SIGTERM then SIGKILL on QEMU process.

## Implementation Plan

### Tasks

- [x] **Task 1:** Add image directory and KVM helpers. File: `pysandboxes/remote/qemu_image.py` (new). Implement `get_vm_images_dir()`, `get_default_image_path(python_version, arch)`, `ensure_image(path)`, `is_kvm_available()`. Use PYSANDBOXES_VM_IMAGES_DIR or $XDG_DATA_HOME/vm-images; sys.version_info[:2], platform.machine().
- [x] **Task 2:** Add abstract VMSSEDaemon. File: `pysandboxes/remote/vm_sse_daemon.py` (new). Define VMSSEDaemon(BaseSubProcessDaemon) with __slots__; document that subclasses override _re_start_cmd to not append --_named-pipe to args. Follow daemon-lifecycle-pattern.
- [x] **Task 3:** QemuSSEDaemon parse_rules and subprocess_cmd. File: `pysandboxes/remote/qemu_sse_daemon.py` (new). parse_rules for qemu.* to os_sandbox_params. subprocess_cmd builds QEMU cmd: image, -enable-kvm if KVM, -net user,hostfwd=..., virtio-9p (temp), virtio-serial QGA. Use qemu_image helpers; GUEST_PORT fixed.
- [x] **Task 4:** QemuSSEDaemon _re_start_cmd and lifecycle. File: `qemu_sse_daemon.py`. Override _re_start_cmd to call launch_sandbox(args, ...) without appending --_named-pipe. _start/_stop/_shutdown; _shutdown tries QGA then SIGTERM/SIGKILL. Reuse _re_start.
- [x] **Task 5:** Inject netfilter rules into guest payload. File: `qemu_sse_daemon.py`. Call rule_to_netfilter and include list in pipe payload; guest iptables-restore. See UnshareSetupConfig.netfilter_rules.
- [x] **Task 6:** Register qemu; allow in main_sandbox. File: `_os_sandbox.py`: add "qemu": QemuSSEDaemon to providers_factory. File: `main_sandbox.py`: add "qemu" to allowed os_sandbox tuple.
- [x] **Task 7:** python_sb: no python_cmd for qemu. File: `python_sb.py`. If all_rules.os_sandbox == "qemu" pass only cmd to launch_sandbox; else cmd + python_cmd. pipe_path and process_config still passed.
- [x] **Task 8:** Standard image download. File: qemu_image.py + optional CLI. Download default image to get_vm_images_dir(); optional checksum; expose e.g. python -m pysandboxes.remote.qemu_fetch_image. If image exists, use it. First version can raise with clear message if missing.
- [x] **Task 9:** Document guest image contract and standard directory. File: docs or README. Document guest contract (Python, SSE server, pipe config, iptables-restore, qemu-guest-agent) and directory layout for reuse.
- [x] **Task 10:** En fin d’implémentation, vérifier l’exécution des tests dans cet ordre : (1) `tests/integration_tests/test_usage_with_providers.py` (ajouter `qemu` à la liste des providers testés, avec skip si QEMU/image non disponibles si besoin), (2) `tests/containers/test_containers.py`. S’assurer que les deux suites passent (ou skip de manière explicite pour qemu quand l’environnement ne le permet pas).

### Acceptance Criteria

- [ ] **AC 1:** Given config with `os-sandbox=qemu` and no `qemu.image`, when the daemon starts, then the standard image for current Python version is resolved; if file exists it is used, else download or clear error.
- [ ] **AC 2:** Given an image already at the standard directory path, when the provider starts with default image, then the provider uses it without re-downloading.
- [ ] **AC 3:** Given `os-sandbox=qemu` and a valid image path, when the daemon is started and the guest is up, then the client can call into the sandbox via SSE.
- [ ] **AC 4:** Given `/dev/kvm` available and readable, when QEMU is started, then the command includes `-enable-kvm`; given not available, then no `-enable-kvm` (TCG).
- [ ] **AC 5:** Given socket rules in config, when the guest has started, then config and iptables rules were delivered via the pipe and enforced in the VM.
- [ ] **AC 6:** Given the daemon is running, when shutdown is requested, then QGA guest-shutdown is attempted; on timeout/unavailable, then SIGTERM then SIGKILL on QEMU.
- [ ] **AC 7:** Given no override env, when the image directory is resolved, then it equals $XDG_DATA_HOME/vm-images (or ~/.local/share/vm-images); when PYSANDBOXES_VM_IMAGES_DIR is set, that path is used; layout documented.
- [ ] **AC 8:** Given python_sb with os-sandbox=qemu, when the command is built, then only the QEMU command is passed to launch_sandbox (no Python script args).
- [ ] **AC 9:** Given invalid or missing qemu.* params, when parse_rules is called, then errors are appended and returned params/rest are consistent; valid qemu.image, qemu.memory, qemu.use_kvm in os_sandbox_params.
- [ ] **AC 10:** Given l’implémentation terminée, when on lance la validation, then (1) `tests/integration_tests/test_usage_with_providers.py` est exécuté en premier et passe (ou skip explicite pour qemu si env non dispo), puis (2) `tests/containers/test_containers.py` est exécuté et passe (ou skip explicite pour qemu si besoin).

## Additional Context

### Dependencies

- Host: QEMU system emulation (`qemu-system-x86_64` or arch-specific), Python 3.10+, existing pysandboxes deps.
- Guest image: Python (same major.minor as host), pysandboxes (or SSE server), iptables, script for pipe config + iptables-restore, qemu-guest-agent (recommended). Standard image is distributed as a pre-built artifact (download URL + optional checksum); stored in standard directory for reuse.

### Testing Strategy

- Unit tests for KVM detection, image path resolution, QEMU command-line building (no real QEMU).
- Integration tests: optional (mark `requires` or env) with a minimal guest image: start provider, one round-trip call, shutdown via QGA or fallback.
- **Vérification en fin d’implémentation (ordre obligatoire)** : exécuter d’abord `tests/integration_tests/test_usage_with_providers.py` (inclure le provider `qemu` dans la liste testée ; skip si QEMU ou image non disponibles), puis `tests/containers/test_containers.py`. Les deux suites doivent passer (ou skip explicite pour qemu lorsque l’environnement ne permet pas l’exécution).

### Notes

- TCG is slower; document for users.
- Standard image is pre-built and distributed (download only); image build/recipe is out of scope. The guest image contract (entrypoint, pipe, iptables, QGA) and the standard directory layout are documented so the same image can be reused by other tools or already present on disk.

## Review Notes

- Adversarial review completed (quick-dev step-05).
- Findings: 10 total, 5 fixed (F1–F5), 5 noted/skipped (F6–F10 low/notes).
- Resolution: auto-fix for real findings — F1 main_sandbox assert restored with qemu; F2 DEFAULT_IMAGE_PREFIX set to pysandboxes-python; F3 subprocess/none re-enabled in test provider lists; F4 unused imports removed; F5 qemu.memory validated (digits only).
