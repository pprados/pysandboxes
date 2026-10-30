---
name: pysandboxes-os-provider
description: Use when adding a new OS-sandbox provider (os-sandbox=<name>) to pysandboxes, e.g. a Windows, macOS or other-OS isolation backend, or a new Linux technology next to the providers of `_PROVIDER_SPECS` (landlock, bwrap, firejail, unshare, qemu, sandbox-exec, ...). Covers the daemon class, the platform registry, rule enforcement, tests, CI, documentation, changelog and pull request requirements.
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

Work through these phases in order. Keep findings and decisions in the implementation plan or task notes; do not start provider implementation until technical analysis and planning are complete. Branch from `develop` and open the pull request against it, never `master`.

### 1. Technical feasibility analysis

Investigate the actual OS primitive and build small, disposable experiments when documentation cannot establish behavior. Determine how the solution handles filesystem boundaries (read-only/read-write exposure, hidden paths, symlinks and outside access), network boundaries (default deny, allow rules and inbound ports), DNS and possible bypasses, environment rules, process and privilege boundaries, IPC, cleanup, host prerequisites, container restrictions, failure behavior, and the existing daemon/child transport.

For every rule kind (`expose-ro`, `expose-rw`, `ignore=`, `net=`, and env rules), record the primitive, experiment or evidence, gaps, and implementation strategy. Distinguish OS enforcement from Python-only enforcement. For unsupported rules, define an explicit warning and documented limitation. Define `unavailable_reason()` probes and fail-closed behavior. Choose the self-restricting or launcher model only after this analysis. For non-Linux targets, prove the subprocess/SSE transport using `.github/workflows/cross-os.yml` first.

This phase is complete when findings identify a viable design, prerequisites and limitations, and an answer for every rule kind. If a fundamental requirement cannot be met safely, stop and report the blocker.

### 2. Integration plan

Before implementation, create an ordered plan using every applicable item in `references/registration-points.md`. Include provider module/model, lazy imports, registry and registration points; unit and integration tests; image; documentation; CI on each claimed platform; and security follow-up.

The plan must require a new row in `ALL_OS_SANDBOX` and successful runs of **both** shared suites: `test_usage_with_providers.py` and `test_guards_with_providers.py`. The provider must pass every shared case applicable to its platform. Do not deselect or silently skip cases; CI uses `PYSANDBOXES_FAIL_ON_SKIP=1`.

If OS-level `net=` filtering is claimed, include tests in `tests/integration_tests/test_os_netfilter.py` with the Python guard disabled and a negative control. Shared suites alone cannot prove the OS filter works. Otherwise, record the lack of OS-level enforcement and warning behavior.

Include a provider-specific Docker/Podman image, its build and smoke-test integration, and instructions for running it. Investigate host privileges and runtime constraints. If the target OS or runtime makes such an image impossible, establish that in feasibility analysis and plan the closest useful container validation with evidence.

Include the `CHANGELOG.md` entry and the pull request requirements of `CONTRIBUTING.md` (see "Repository requirements" below). Include a dedicated `wiki/<name>.md` page and updates to existing pages identified from the Documentation table in `references/registration-points.md` and a repository-wide search for the latest comparable provider (currently landlock). List the intended change for each page and update relevant existing pages too.

Include CI for every claimed platform. Update `.github/workflows/cross-os.yml` for supported non-Linux platforms. If hosted runners cannot provide the required capability, plan a GitHub Actions VM route or reproducible local VM validation. Do not add a platform tag until its provider suites have passed there.

If analysis or integration exposes a possible vulnerability in shared behavior or another provider, plan remediation and regression tests for every affected provider. Do not close integration while a cross-provider vulnerability is fixed only in the new provider. The plan is complete when every item has an implementation location and verifiable completion condition, and each feasibility risk has a disposition.

### 3. Implement and verify

Implement the planned provider and fail closed if activation fails. Probe host prerequisites in `unavailable_reason()`. Keep test-environment-only constraints (container, CI runner, missing privilege) in `provider_skip_reason()` in `tests/integration_tests/_env.py`, never in provider availability logic. Run planned unit/provider suites, both shared suites, and OS network-filter tests when applicable. Build and smoke-test the image. Run provider suites on every claimed OS with skips treated as failures. Resolve newly discovered shared vulnerabilities across affected providers and add regression coverage.

### 4. Document and close out

Write `wiki/<name>.md` covering how it works, prerequisites, limitations, and how to run it, including Docker/Podman usage. Update the existing pages listed in the plan and the rule-enforcement/deployment table in `wiki/os-providers.md`. Record each rule as enforced or not enforced; never imply Python-only checks provide OS confinement. Finish only when provider-specific and shared suites pass on every claimed platform, the image is validated, documentation is consistent, and security follow-ups are complete or reported as blockers.

## Implementation details

1. **Choose the model**. Deciding question: does the OS primitive restrict the *current* process, or must it be applied when the process is *created*?
   - **Self-restricting** (landlock): subclass `SubProcessDaemon`; the child calls `update_rules_and_activate()` before the Python guards are armed (`py_sandbox.py`, `activate_sandboxes`), translates the rules and restricts itself irrevocably.
   - **Launcher** (bwrap, firejail, unshare): subclass `BaseSubProcessDaemon`; override `subprocess_cmd()` to wrap the child command, optionally from a `pysandboxes/templates/<name>.template`.
   - Provider-specific profile keys (`<name>.<key>=`, e.g. `qemu.use_kvm`) are parsed by `parse_rules()`.

2. **Fail closed**. If activation fails, the sandboxed process exits (`sys.exit(-1)` in landlock). It never runs the code unrestricted.

3. **Cover every rule kind**: `expose-ro`, `expose-rw`, `ignore=`, `net=`, env rules. For each one, the provider either enforces it, or logs a warning when `py-sandbox=False` leaves it unenforced (model: `_warn_ignore_rules_are_not_enforced` in landlock). Record the result (✅/❌) in `wiki/os-providers.md`. A rule silently not enforced is the failure this step prevents.

4. **Probe the host** in the classmethod `unavailable_reason()`: binary, kernel feature, OS version. Return a human-readable reason or `None`.

5. **Register the provider**: every point listed in `references/registration-points.md`. The platform tag in `_PROVIDER_SPECS` is a claim: "the CI job of that OS must run the provider suites before a value is added".

6. **Test**:
   - Unit tests for rule translation in `tests/unit_tests/remote/test_<name>_*.py`.
   - Integration suite in `tests/integration_tests/remote/test_<name>.py`.
   - The shared suites `test_usage_with_providers.py` and `test_guards_with_providers.py` must pass with the new row of `ALL_OS_SANDBOX`.
   - If the provider enforces `net=` at the OS level, add it to `_PROVIDERS` in `tests/integration_tests/test_os_netfilter.py`. With `py-sandbox=false`, it proves under `python-sb` and in daemon mode that the OS filter alone drops a destination outside the rules, with a negative control. The shared suites cannot show this: the Python socket guard refuses in place of a broken filter, which is how the bwrap and qemu filters stayed broken unnoticed. A provider that does not enforce `net=` records ❌ in `wiki/os-providers.md` instead (step 3).
   - The tests follow the rules of the "Tests" section of `CONTRIBUTING.md`: a test must be able to fail, with a negative control run without the sandbox, refusals asserted through `sandbox_denials()`, and a narrow `pytest.raises`. Never set `OS_SANDBOX=none` to make a suite pass.

These implementation details complement the phases above; the documentation scope is the one defined in the integration plan.

## Resources

- `references/registration-points.md`: every file and identifier to edit, Linux-only assumptions to avoid, and the verification commands. Load it before editing.

## Conventions to respect

- Never import platform-only modules (`fcntl`, `ctypes` bindings of one OS, ...) at the top of a module reachable from other platforms: the registry is read without importing the provider, keep it so.
- A provider that cannot express a rule says so (warning + ❌ in the wiki); it does not approximate it silently.
- Never modify the root `.py-sandboxes` configuration.
- Import layering is enforced by `tests/unit_tests/test_architecture.py` (pytestarch): a provider never imports another provider nor an entry point, and only `_os_sandbox` and `python_sb` import `remote`. A new module that breaks a rule gets its import fixed, not the rule.

## Repository requirements

- **Code**: type hints everywhere, Python 3.11 syntax (`str | None`), docstrings on public APIs, lines of at most 120 characters, `black` formatting. Every new file starts with `# Copyright (c) 2026, Philippe PRADOS` and `# License: Apache V2`. No useless comments.
- **Changelog**: add one user-facing line, with no implementation detail, to the open `## [0.0.0] - 202X-XX-XX` entry of `CHANGELOG.md`, under `### Added`. Before the first public release the entry has no `### Changed` or `### Fixed`. Tick the provider in the OS-Sandbox column of the table at the top (and the OS column for a new platform). Never date the entry nor add a version: `make publish-*` does.
- **Dependencies**: `uv` only; run `make lock` when `pyproject.toml` changes.
- **Pull request**: use the `security-model.md` template (`.github/PULL_REQUEST_TEMPLATE/`). Say which layer the change touches (Python or OS) and give a test proving the refusal holds. Commit subjects follow Conventional Commits (`feat(provider): ...`, `test(integration): ...`, `docs: ...`).
- **Before the pull request**: `make format`, `make validate`, and `make integration-tests` (a provider always qualifies).
- **Documentation**: a new known weakness goes into `wiki/weaknesses.md`; what the provider holds against compiled code goes into `wiki/audit-python-security.md`.
