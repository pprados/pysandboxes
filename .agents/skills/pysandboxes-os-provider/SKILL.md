---
name: pysandboxes-os-provider
description: Use when adding a new OS-sandbox provider (os-sandbox=<name>) to pysandboxes, e.g. a Windows, macOS or other-OS isolation backend, or a new Linux technology next to landlock, bwrap, firejail, unshare and qemu. Covers the daemon class, the platform registry, rule enforcement, tests, CI and documentation.
---

# Pysandboxes OS Provider

## Overview

An OS provider is the kernel-enforced layer (`os-sandbox=<name>`) around the Python guards (`py-sandbox`). It is a `BaseDaemon` subclass, declared in the registry `_PROVIDER_SPECS` (`pysandboxes/_os_sandbox.py`) with the `sys.platform` values it runs on, and loaded lazily through `providers_factory`.

Do not copy code from this skill: read the live providers.
- `pysandboxes/remote/landlock_daemon.py`: **self-restricting** model.
- `pysandboxes/remote/bwrap_sse_daemon.py`: **launcher** model.
- `pysandboxes/base_daemon.py`, `pysandboxes/remote/client_subprocess_sse_daemon.py`: the interface and the SSE transport both reuse.

## When to use this skill

- The user wants a sandbox backend for Windows, macOS, BSD or another OS.
- The user wants a new Linux isolation technology as a provider.
- The user wants to port an existing provider to another platform (new platform tag).

## Workflow

0. **Prove the transport on the target OS first** (non-Linux only). Both models run the code in a child reached over SSE (`SubProcessDaemon`). `.github/workflows/cross-os.yml` runs `subprocess` on macOS and Windows on demand, "until both runners are green". Run it on the target OS and get it green before writing the provider: a provider inherits every transport failure.

1. **Choose the model**. Deciding question: does the OS primitive restrict the *current* process, or must it be applied when the process is *created*?
   - **Self-restricting** (landlock): subclass `SubProcessDaemon`; the child calls `update_rules_and_activate()` before the Python guards are armed (`py_sandbox.py`, `activate_sandboxes`), translates the rules and restricts itself irrevocably.
   - **Launcher** (bwrap, firejail, unshare): subclass `BaseSubProcessDaemon`; override `subprocess_cmd()` to wrap the child command, optionally from a `pysandboxes/templates/<name>.template`.
   - Provider-specific profile keys (`<name>.<key>=`, e.g. `qemu.use_kvm`) are parsed by `parse_rules()`.

2. **Fail closed**. If activation fails, the sandboxed process exits (`sys.exit(-1)` in landlock). It never runs the code unrestricted.

3. **Cover every rule kind**: `expose-ro`, `expose-rw`, `ignore=`, `net=`, env rules. For each one, the provider either enforces it, or logs a warning when `py-sandbox=False` leaves it unenforced (model: `_warn_ignore_rules_are_not_enforced` in landlock). Record the result (✅/❌) in `wiki/os-providers.md`. A rule silently not enforced is the failure this step prevents.

4. **Probe the host** in the classmethod `unavailable_reason()`: binary, kernel feature, OS version. Return a human-readable reason or `None`. Test-environment quirks only (container, CI runner) go into `provider_skip_reason()` in `tests/integration_tests/_env.py`, never into the provider.

5. **Register the provider**: every point listed in `references/registration-points.md`. The platform tag in `_PROVIDER_SPECS` is a claim: "the CI job of that OS must run the provider suites before a value is added".

6. **Test**:
   - Unit tests for rule translation in `tests/unit_tests/remote/test_<name>_*.py`.
   - Integration suite in `tests/integration_tests/remote/test_<name>.py`.
   - The shared suites `test_usage_with_providers.py` and `test_guards_with_providers.py` must pass with the new row of `ALL_OS_SANDBOX`.
   - Every integration test runs in CI, with `PYSANDBOXES_FAIL_ON_SKIP=1`. No row is deselected or silently skipped.

7. **Ask which docs to adjust, then document**. Before editing any documentation, present to the user the list of pages to change, built from the Documentation table of `references/registration-points.md` and from the landlock grep (pages it shows that the table misses), with one line per page saying what changes. Ask the user to confirm, remove or add pages, and to say what the new page must cover. Then write `wiki/<name>.md` (how it works, prerequisites, limitations, running it) and update the confirmed pages. Do not edit a documentation page the user has not confirmed.

## Resources

- `references/registration-points.md`: every file and identifier to edit, Linux-only assumptions to avoid, and the verification commands. Load it before editing.

## Conventions to respect

- Never import platform-only modules (`fcntl`, `ctypes` bindings of one OS, ...) at the top of a module reachable from other platforms: the registry is read without importing the provider, keep it so.
- A provider that cannot express a rule says so (warning + ❌ in the wiki); it does not approximate it silently.
- Never modify the root `.pysandboxes` configuration.
