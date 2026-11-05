# QEMU microvm Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed Linux x86_64 `os-sandbox=qemu-microvm` provider using direct kernel boot and virtio-mmio.

**Architecture:** Register a distinct provider backed by a subclass in the existing QEMU daemon module. Share image,
NoCloud, SSE, staging, netfilter, console, and lifecycle code; override only artifact resolution and QEMU device
construction. Extend provider metadata with supported CPU architectures so unsupported hosts get no test row.

**Tech Stack:** Python 3.11, pytest, QEMU/KVM/TCG, virtio-mmio, cloud-init NoCloud, virtio-9p, 7zip, Docker/Podman/Kubernetes, GitHub Actions.

**Spec:** `.superpowers/spikes/qemu-microvm/feasibility.md`

## Global Constraints

- Branch from `develop`; target `develop`, never `master`.
- Linux x86_64 only until another architecture has its own passing provider suites.
- Preserve `os-sandbox=qemu` behavior and supported architectures.
- Fail closed on boot-artifact, mount, netfilter, MMIO-capacity, and startup failures.
- Never omit or approximate `expose-ro`, `expose-rw`, `ignore=`, `net=`, or env rules silently.
- Keep platform-specific imports lazy and provider modules independent.
- Python 3.11 syntax, types everywhere, public docstrings, 120-character project line limit.
- Every new file gets the 2026 copyright and Apache V2 header.
- Do not modify the root `.py-sandboxes` file.

## Review Focus

## Execution decisions (2026-11-05)

- User override: implement on `feature/qemu-microvm`; no merge, push, publication, or PR during implementation.
- User override: run new-provider unit/integration/sample checks during development; defer other-provider integration and broad regressions to Task 10. Task 1 retains focused QEMU unit preservation proof.
- No separate persistent progress/todo ledger: use this approved plan and task reports for recovery, per repository instructions.
- Container image publication in Task 7 means build/CI wiring only; external publication is deferred.

### Preflight interface review

| Tasks | Shared interface | Finding |
|---|---|---|
| 1, 3 | Launch assets and machine command in QEMU daemon | Preserve PC arguments before subclass override. |
| 2, 3 | Matched kernel/initrd resolver | Resolver raises before launch; cache follows image identity. |
| 2, 7 | Image extraction prerequisites | Container and host setup both require 7zip. |
| 3, 4 | Shared guest bootstrap | Mount failures must terminate both providers; old-provider runtime proof deferred to 10. |
| 3, 5 | Class registry | Same-module subclass avoids provider-import layering violation. |
| 5, 6 | Provider rows and platform metadata | Architecture filter must precede parametrization. |
| 5, 7, 8 | Provider matrix | New row remains x86-only in CI, images, samples. |
| 6, 9 | Security claims | Documentation may claim only controls proven by native tests. |
| 7, 8 | Image/cache and samples | Keep KVM and TCG results distinct. |
| 8, 9 | Canonical profile and copies | Update copies from template, never root profile. |
| 1, 10 | PC behavior preservation | Focused units now; broad runtime proof last. |
| 2, 10 | Supported Python image mapping | Each mapped upstream image needs artifact proof. |
| 4, 10 | Shared security fix | Both providers need mount failure proof before completion. |
| 7, 10 | Deployment validation | Missing engines/capabilities are explicit blockers, not passing gates. |
| 9, 10 | Ship claims | Roadmap completion depends on all gates. |

| Task | Internal consistency |
|---|---|
| 1 | Characterization before extraction; compatible. |
| 2 | Discovery, atomic cache and explicit overrides; compatible. |
| 3 | Strict MMIO command requires runtime slot probe; compatible. |
| 4 | Immediate old-provider integration conflicts with user order; deferred to 10. |
| 5 | Architecture metadata must keep existing public platform lists compatible. |
| 6 | Native tests and shared suites required; no silent skip. |
| 7 | Publication conflicts with implementation-only scope; wiring only. |
| 8 | Existing fast sample target cannot substitute for VM lane. |
| 9 | Roadmap stays pending if deployment gates incomplete. |
| 10 | PR creation conflicts with deferred integration; prepare evidence locally only. |

- A changed cloud image must invalidate cached kernel/initrd artifacts; Task 2 tests digest/version mismatch.
- More MMIO consumers than the machine exposes must fail before guest execution; Task 3 tests the boundary.
- A failed 9p or ignore mount must stop the guest; Task 4 injects both failures.
- Linux aarch64 must not advertise or parametrize this provider; Task 5 tests host metadata.
- TCG success must not be reported as KVM security or performance evidence; Tasks 6 and 8 keep separate rows/results.

---

### Task 1: Preserve current QEMU behavior while creating a shared command seam

Completed: `a2c1d904`; independent task review passed; 444 focused QEMU unit tests before/after.

**Files:**
- Modify: `pysandboxes/remote/qemu_sse_daemon.py`
- Test: `tests/unit_tests/remote/test_qemu_restart_cmd.py`
- Test: `tests/unit_tests/remote/test_qemu_virtfs_policy.py`
- Test: `tests/unit_tests/remote/test_qemu_hostfwd_loopback.py`

**Interfaces:**
- Produces: `_prepare_qemu_launch(...) -> _QemuLaunchAssets` and `QemuSSEDaemon._machine_command(...) -> Args`.
- Preserves: byte-for-byte argument semantics of the existing PC-machine QEMU command.

- [ ] Add characterization tests for root disk, NoCloud disk, `-nic`, each `-virtfs`, guest-agent devices, KVM, memory, and console args.
- [ ] Run the focused tests and confirm they pass before refactoring.
- [ ] Extract launch-asset preparation from device construction; keep the current provider's output unchanged.
- [ ] Run all QEMU unit tests: `uv run pytest -q tests/unit_tests/remote -k qemu`.
- [ ] Commit: `refactor(provider): isolate qemu machine command construction`.

### Task 2: Resolve and verify matched microvm boot artifacts

Completed implementation: `bfeb42c2`, `95f5e3f7`, `eaeff8e6`; independent review passed after concurrency fix.
54 focused tests and 4388 full units passed (26 skipped, 5 xfailed). Actual upstream extraction passed all
Python 3.11–3.14 mappings, including separate boot filesystem on Ubuntu 24.04. CI matrix automation remains Task 7.

**Files:**
- Create: `pysandboxes/remote/qemu_microvm_boot.py`
- Modify: `pysandboxes/remote/qemu_fetch_image.py`
- Modify: `Dockerfile-qemu`
- Modify: `scripts/install_qemu.sh`
- Modify: `scripts/setup/lib.sh`
- Modify: `scripts/setup/doctor.sh`
- Modify: `scripts/setup/setup-linux.sh`
- Test: `tests/unit_tests/remote/test_qemu_microvm_boot.py`
- Test: `tests/unit_tests/remote/test_qemu_image_download.py`

**Interfaces:**
- Consumes: root image from `get_default_image_path()` and optional `qemu.microvm_kernel` / `qemu.microvm_initrd`.
- Produces: `ensure_microvm_boot_artifacts(image: Path, params: Mapping[str, Any]) -> tuple[Path, Path]`.

- [ ] Write tests for explicit paths, missing files, atomic cache, image-change invalidation, mismatched kernel/initrd names, malformed archives, and interrupted extraction.
- [ ] Add fixture images representing the supported Ubuntu partition layouts without committing full cloud images.
- [ ] Implement `7z` discovery of the partition containing a matched `vmlinuz-*` and `initrd.img-*`; never use a fixed partition number.
- [ ] Cache files beside the VM cache with source image identity and verify readability before returning.
- [ ] Add `7zip` to setup, doctor, and provider image prerequisites; keep user overrides usable without extraction.
- [ ] Test extraction against all upstream images mapped to Python 3.11, 3.12, 3.13, and 3.14 in CI.
- [ ] Commit: `feat(provider): prepare qemu microvm boot artifacts`.

### Task 3: Build the strict microvm command and preflight MMIO capacity

Completed implementation: `95fde173`, `0246878c`, `bc0bbd28`; independent task review passed after two fix rounds.
455 focused QEMU units passed. Eleven standalone KVM transport/boot probes passed; real TCG and KVM capacity
boundaries passed separately. Actual strict configuration exposes 8 MMIO transports in both modes on this host;
the runtime probe, not the earlier spike's 24-device observation, defines the launch budget. Unit tests do not
require QEMU; integration collection runs TCG and adds KVM only when available, without skips.
This is not full daemon/provider validation: registration and native shared contracts remain pending.

### Session checkpoint

Session reached the repository's 30,000-token budget after Task 3 and its scoped review fixes. Tasks 4–10 remain
unimplemented. Resume at Task 4 in `/tmp/pysandboxes-qemu-microvm`, branch `feature/qemu-microvm`.
Task reports and review packages are under `.superpowers/sdd/2026-11-05-qemu-microvm-provider/`.
Do not repeat completed Tasks 1–3. No merge, push, image publication, or PR has occurred.
Next: fail-closed shared guest mounts, architecture-aware registration, new-provider full integration and samples,
image/CI/documentation, then broad old-provider regressions last. No shipping or security-completeness claim yet.

**Files:**
- Modify: `pysandboxes/remote/qemu_sse_daemon.py`
- Modify: `pysandboxes/remote/qemu_setup.py`
- Test: `tests/unit_tests/remote/test_qemu_microvm_cmd.py`
- Test: `tests/integration_tests/remote/test_qemu_microvm.py`

**Interfaces:**
- Produces: `QemuMicrovmSSEDaemon(QemuSSEDaemon)` in the same module.
- Produces: `microvm_mmio_capacity(qemu_binary: str) -> int` and a pre-launch device-count check.

- [ ] Write command tests requiring `microvm,acpi=off,pcie=off`, explicit serial, direct kernel/initrd, `-no-reboot`, MMIO block/network/9p devices, and no PCI device.
- [ ] Write negative tests showing every current PCI fragment is rejected by the strict machine.
- [ ] Write boundary tests proving exact-capacity launch and one-over-capacity fail before QEMU starts.
- [ ] Implement root and NoCloud disks with `if=none` plus `virtio-blk-device`; use `virtio-net-device`, `-fsdev` plus `virtio-9p-device`, and no unused guest-agent controller.
- [ ] Generate network config matching the MMIO interface by behavior, not a hard-coded `en*` name.
- [ ] Add `console=ttyS0 root=/dev/vda1 ro reboot=t` and terminate through `-no-reboot`; preserve console/result parsing.
- [ ] Port the disposable kernel/rootfs/cloud-init/network/9p probe into the integration suite with cached artifacts.
- [ ] Commit: `feat(provider): launch qemu microvm with virtio mmio`.

### Task 4: Make guest setup fail closed for both QEMU providers

**Files:**
- Modify: `pysandboxes/remote/qemu_setup.py`
- Modify: `wiki/weaknesses.md`
- Test: `tests/unit_tests/remote/test_qemu_setup.py`
- Test: `tests/integration_tests/remote/test_qemu.py`
- Test: `tests/integration_tests/remote/test_qemu_microvm.py`

**Interfaces:**
- Preserves: shared bootstrap behavior except mount failures now terminate before user code.

- [ ] Add fault-injection tests where required 9p, read-only, writable, and ignore-overlay mounts fail.
- [ ] Verify each failure prevents the SSE ready marker and user-code side effects under both providers.
- [ ] Remove `|| true` from required mounts; classify any truly optional mount explicitly and warn.
- [ ] Re-run current QEMU provider integration tests to catch shared regressions.
- [ ] Update the known weakness only after the reproducer is green for both providers.
- [ ] Commit: `fix(security): fail closed on qemu guest mount errors`.

### Task 5: Register architecture-aware provider metadata

**Files:**
- Modify: `pysandboxes/_os_sandbox.py`
- Modify: `pysandboxes/remote/main_sandbox.py`
- Modify: `pysandboxes/__init__.py`
- Modify: `tests/integration_tests/_env.py`
- Modify: `tests/conftest.py`
- Modify: `tests/unit_tests/test_provider_platforms.py`
- Modify: `tests/unit_tests/test_integration_rows.py`
- Test: `tests/unit_tests/test_architecture.py`

**Interfaces:**
- Produces: provider metadata that checks both `sys.platform` and normalized `platform.machine()` without importing providers.
- Produces: public provider name `qemu-microvm` mapped to `QemuMicrovmSSEDaemon`.

- [ ] Write tests for Linux x86_64 inclusion, Linux aarch64 exclusion, and unchanged lists on macOS/Windows.
- [ ] Extend `_PROVIDER_SPECS` metadata without eagerly importing QEMU modules.
- [ ] Add `qemu-microvm` to `ALL_OS_SANDBOX`; add an opt-in `qemu-microvm-tcg` row only if KVM CI cannot cover TCG elsewhere.
- [ ] Map row-specific profile lines and timeouts without weakening `PYSANDBOXES_FAIL_ON_SKIP=1`.
- [ ] Run `uv run pytest tests/unit_tests/test_provider_platforms.py tests/unit_tests/test_architecture.py tests/unit_tests/test_integration_rows.py`.
- [ ] Commit: `feat(provider): register qemu microvm on linux x86`.

### Task 6: Prove all shared and OS-only security contracts

**Files:**
- Modify: `tests/integration_tests/test_usage_with_providers.py`
- Modify: `tests/integration_tests/test_guards_with_providers.py`
- Modify: `tests/integration_tests/test_os_file_confinement.py`
- Modify: `tests/integration_tests/test_os_netfilter.py`
- Modify: `tests/integration_tests/test_native_readonly_share.py`
- Modify: `tests/integration_tests/test_temp_cleanup.py`
- Modify: `tests/integration_tests/test_sandbox_recovery.py`
- Modify: `tests/integration_tests/py-sandbox-test.profile`

**Interfaces:**
- Consumes: registered provider and shared `qemu.*` settings.
- Produces: KVM and TCG evidence separated by test row.

- [ ] Add provider timeouts and environment setup without deselecting any shared case.
- [ ] Run both mandatory shared suites with skips fatal.
- [ ] Add native read/write/outside-path tests in both `python-sb` and daemon modes with Python guards off.
- [ ] Add `qemu-microvm` to OS netfilter tests; prove deny and allow controls with Python guards off and a host negative control.
- [ ] Prove native `expose-ro` write refusal, `ignore=` masking, env stripping, temp cleanup, restart, and no surviving QEMU process.
- [ ] Run KVM on a capable host and forced TCG separately; record boot time, first-SSE time, RSS, and exit cleanup.
- [ ] Commit: `test(integration): cover qemu microvm security contracts`.

### Task 7: Build, smoke-test, and publish the provider image

**Files:**
- Create: `Dockerfile-qemu-microvm`
- Modify: `Makefile`
- Modify: `tests/containers_tests/test_containers.py`
- Modify: `tests/unit_tests/test_smoke_test_images.py`
- Modify: `.github/scripts/smoke-test-images.sh`
- Modify: `.github/scripts/refresh-images.sh`
- Modify: `.github/workflows/images.yml`
- Modify: `.github/workflows/containers.yml`
- Modify: `.github/workflows/integration.yml`

**Interfaces:**
- Produces: `python-sb-qemu-microvm:<python>` and `build-image-qemu-microvm`.

- [ ] Write smoke-test unit expectations before changing the script.
- [ ] Build from the base image with QEMU, `7zip`, ISO tooling, firewall tools, root image, and verified boot artifacts.
- [ ] Add build stamps, all-image aggregation, cleanup, minikube loading, refresh, and publication.
- [ ] Run container tests under Docker and Podman without privilege, with optional `/dev/kvm`, then Kubernetes with and without KVM.
- [ ] Make smoke tests boot the guest and verify its iptables backend, not only binary presence.
- [ ] Add x86_64 integration CI with `PYSANDBOXES_FAIL_ON_SKIP=1`; do not add non-x86 platform claims.
- [ ] Commit: `build(provider): add qemu microvm image and ci`.

### Task 8: Integrate every sample without hiding VM cost

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/samples.yml`
- Modify: generated/sample profiles containing the QEMU configuration block
- Modify: affected sample lock files only if dependencies change

**Interfaces:**
- Produces: an explicit microvm sample matrix, separate from fast provider rows.

- [ ] Add a `SAMPLE_VM_PROVIDERS` lane containing `qemu` and `qemu-microvm`; do not silently call integration coverage sample coverage.
- [ ] Run every sample on one supported Python under KVM nightly, with live-model gates still disabled.
- [ ] Run every sample on Python 3.11 through 3.14 before minor/final release; cache one image/artifact set per Python.
- [ ] Add TCG smoke coverage for one representative sample and keep its timeout/result distinct from KVM.
- [ ] Regenerate or update every shipped complete profile from the canonical template; avoid hand-edit drift.
- [ ] Verify `make sample-tests` and the new VM sample target locally where KVM exists.
- [ ] Commit: `test(samples): run samples with qemu microvm`.

### Task 9: Document guarantees, operation, and limits

**Files:**
- Create: `wiki/qemu-microvm.md`
- Modify: `wiki/os-providers.md`, `wiki/Home.md`, `wiki/tests.md`, `wiki/implementation.md`, `wiki/configuration.md`
- Modify: `wiki/docker-hub.md`, `wiki/roadmap.md`, `wiki/alternatives.md`, `wiki/use-cases.md`
- Modify: `wiki/audit-python-security.md`, `wiki/weaknesses.md`
- Modify: `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`, `AGENTS.template.md`
- Modify: `pysandboxes/templates/py-sandboxes.template`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents: exact OS enforcement, x86/KVM/TCG prerequisites, artifact cache, MMIO limit, container commands, and measured latency.

- [ ] Add provider page with architecture, boot artifacts, configuration, Docker/Podman/Kubernetes, troubleshooting, and cleanup.
- [ ] Add a separate rule-enforcement column; mark only integration-proved controls as supported.
- [ ] State that TCG lacks QEMU's hardware-virtualization isolation guarantee and that microvm does not prevent hypervisor escape.
- [ ] Update every provider list and test/deployment matrix found by the registration search.
- [ ] Mark the roadmap item complete only after all ship gates pass.
- [ ] Add one user-facing line under the open changelog `Added` section and tick the provider table without dating/versioning it.
- [ ] Commit: `docs(provider): document qemu microvm`.

### Task 10: Full gate and maintainer evidence

**Files:**
- Create/update: PR body from `.github/PULL_REQUEST_TEMPLATE/security-model.md`

**Interfaces:**
- Produces: reproducible proof for the Python and OS layers and every claimed deployment.

- [ ] Run `make format`.
- [ ] Run `make validate`.
- [ ] Run `make integration-tests` with KVM and skips fatal.
- [ ] Run forced TCG provider suites and record separate timings.
- [ ] Run `make container-tests`, provider image smoke tests, and the VM sample matrix.
- [ ] Verify every feasibility risk has a test, documented limit, or explicit blocker.
- [ ] Review the final diff against `develop`, not `master`; confirm no unrelated edits.
- [ ] Commit any gate-only correction with its own focused Conventional Commit.
- [ ] Open the PR against `develop`, naming the native refusal test and the residual risks.
