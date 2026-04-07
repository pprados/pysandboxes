---
title: 'Add bwrap (bubblewrap) OS sandbox provider'
slug: add-bwrap-provider
created: '2026-03-12'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.10+', 'pysandboxes daemon pattern', 'bubblewrap (bwrap)', 'pytest']
files_to_modify: ['pysandboxes/_os_sandbox.py', 'pysandboxes/guard_provider.py', 'pyproject.toml', 'tests/unit_tests/test_guard_provider.py', 'tests/integration_tests/remote/test_bwrap.py', 'tests/integration_tests/test_usage_with_providers.py', 'tests/containers/test_containers.py']
code_patterns: ['Daemon Lifecycle Pattern', 'BaseSubProcessDaemon', 'template + rule translation']
test_patterns: ['module-scoped daemon fixture', 'pytest.mark.skipif(not which_command("bwrap"))', 'parametrize os_sandbox']
---

# Tech-Spec: Add bwrap (bubblewrap) OS sandbox provider

**Created:** 2026-03-12

## Overview

### Problem Statement

The codebase has a placeholder for a bwrap provider (`# "bwrap": BWrapDaemon()` in `_os_sandbox.py`) and an existing `pysandboxes/templates/bwrap.template`, but no implementation. Users need a working **bwrap** (bubblewrap) OS-level sandbox provider that integrates with PySandboxes so that `os-sandbox=bwrap` can be used in config and passes all project tests (unit, integration, container).

### Solution

Implement a new daemon class `BWrapSSEDaemon` extending `BaseSubProcessDaemon`, following the same patterns as `FireJailSSEDaemon` and `BubbleJailSSEDaemon`: load `bwrap.template`, translate PySandboxes file rules (bind, ro-bind, ignore) and optional `bwrap.*` config rules into `bwrap` CLI arguments, and build the command as `bwrap [args from template + rules] -- python -m pysandboxes.remote.main_sandbox ...`. Register the provider, add optional extra `bwrap` in pyproject, and add tests so unit, integration, and container test suites pass.

### Scope

**In Scope:**
- New file `pysandboxes/remote/sse_bwrap_daemon.py` with `BWrapSSEDaemon` (subprocess_cmd, parse_rules for `bwrap.*`, update_rules_and_activate).
- Use existing `pysandboxes/templates/bwrap.template`; extend it if needed for minimal viable run (e.g. bind pipe_path, Python stdlib).
- Register `bwrap` in `providers_factory` in `pysandboxes/_os_sandbox.py`.
- Optional dependency `bwrap` in `pyproject.toml` and include in `all` extra.
- Unit tests: ensure `os-sandbox=bwrap` is accepted by guard_provider (and no regressions).
- Integration tests: `tests/integration_tests/remote/test_bwrap.py` (daemon lifecycle, sync/async calls; skip if `bwrap` not installed).
- Integration tests: add `bwrap` to `tests/integration_tests/test_usage_with_providers.py` with skip when `bwrap` not available.
- Container tests: add `bwrap` to `tests/containers/test_containers.py` (with privileged flag as needed for user namespaces in Docker/Podman).

**Out of Scope:**
- Network namespace isolation or slirp4netns for bwrap (same as bubblejail first iteration: localhost).
- Seccomp/custom bwrap profiles beyond what the template and translated rules provide.
- Changing behavior of other providers (firejail, unshare, bubblejail, landlock).

---

## Context for Development

### Codebase Patterns

- **Daemon Lifecycle Pattern** (`.packmind/standards/daemon-lifecycle-pattern.md`): Extend `BaseDaemon` or `BaseSubProcessDaemon`; `__slots__`; implement `_start`, `_stop`, `_shutdown`; provide `call_in_sandbox` and `async_call_in_sandbox`. Base class for this feature: `BaseSubProcessDaemon` (see `sse_client_subprocess_daemon.py`, `sse_firejail_daemon.py`, `sse_bubblejail_daemon.py`).
- **Provider registration**: `pysandboxes/_os_sandbox.py` defines `providers_factory: dict[str, Type]`; keys are provider names (e.g. `"bwrap"`), values are daemon classes. Config rule `os-sandbox=bwrap` is validated in `guard_provider.parse_rules()` by checking `provider in providers_factory`.
- **Subprocess daemon**: Override `subprocess_cmd(all_rules, envs, pipe_path, temp)` to return `(Args, Environ)`. Build command as `[bwrap, ...template args..., ...rule-derived args..., "--", sys.executable, "-u", ..., "-m", "pysandboxes.remote.main_sandbox", ...]`. Use `super().subprocess_cmd(...)` to get the inner Python command and prepend bwrap + args.
- **Template loading**: Same pattern as firejail/unshare: `importlib.resources.files(...)` for `pysandboxes.templates`, read `bwrap.template`, `remove_comments`, `substitute_env_vars` (from `..tools`). Splitting: use `shlex.split` per line or split on spaces for bwrap args.
- **Rule translation**: `parse_rules` for lines starting with `bwrap.` → put in `os_sandbox_params`; other rules passed through. File rules: `BindRule` → `--bind` or `--ro-bind`, `IgnoreRule` → not bind (or blacklist if bwrap supports). Ensure `pipe_path` and Python/runtime paths are bindable so the daemon can start.
- **base_url**: For first iteration, same as bubblejail: `http://localhost:{PORT}` (no network namespace).

### Files to Reference

| File | Purpose |
|------|---------|
| `pysandboxes/remote/sse_firejail_daemon.py` | Reference for template loading, whitelist/bind handling, subprocess_cmd. |
| `pysandboxes/remote/sse_bubblejail_daemon.py` | Minimal subprocess_cmd + parse_rules + base_url localhost. |
| `pysandboxes/remote/sse_client_subprocess_daemon.py` | BaseSubProcessDaemon, subprocess_cmd return shape, launch_sandbox. |
| `pysandboxes/templates/bwrap.template` | Existing bwrap args; may need --ro-bind for /usr, /etc, etc. |
| `pysandboxes/_os_sandbox.py` | providers_factory registration. |
| `pysandboxes/guard_provider.py` | parse_rules uses providers_factory for os-sandbox validation. |
| `tests/integration_tests/remote/test_bubblejail.py` | Pattern for test_bwrap: event_loop, start_daemon_for_tests, skipif bwrap. |
| `tests/integration_tests/remote/test_firejail.py` | Same pattern. |
| `tests/integration_tests/test_usage_with_providers.py` | all_os_sandbox list and _skip_reason. |
| `tests/containers/test_containers.py` | all_os_sandbox ParameterSet list (os_sandbox, py_sandbox, privileged). |
| `tests/unit_tests/test_guard_provider.py` | test_os_sandbox_valid; add bwrap variant. |
| `pyproject.toml` | optional-dependencies firejail, bubblejail, all. |
| `.packmind/standards/daemon-lifecycle-pattern.md` | Daemon contract. |
| `.packmind/commands/create-daemon-implementation.md` | Steps for new daemon. |

### Technical Decisions

- **bwrap first iteration**: No network namespace; base_url = `http://localhost:{PORT}`. Same as bubblejail to minimize scope and avoid slirp4netns complexity.
- **Container tests**: Add bwrap with `privileged: True` (like unshare) so user namespaces work inside Docker/Podman; if CI shows bwrap works without privileged, can be relaxed later.
- **Optional extra**: Add `bwrap = []` (bwrap is system binary, no Python deps) and include in `all` so `pip install pysandboxes[all]` documents bwrap as supported.

---

## Implementation Plan

### Tasks

- [ ] **Task 1: Implement BWrapSSEDaemon**
  - File: `pysandboxes/remote/sse_bwrap_daemon.py` (new)
  - Action: Create module with `BWrapSSEDaemon(BaseSubProcessDaemon)`. Implement `parse_rules`: lines starting with `bwrap.` → dict key/value, rest passed through; return `(ImmutableDict(params), other_rules)`. Implement `update_rules_and_activate`: return `all_rules` (no replacement). Implement `subprocess_cmd`: (1) resolve `bwrap` with `which_command("bwrap")`; exit with suggest_package_installation if missing. (2) Load template from `pysandboxes/templates/bwrap.template` (importlib.resources + Path), remove_comments, substitute_env_vars. (3) Build bwrap args from template lines (shlex.split or split). (4) Add args from `all_rules.os_sandbox_params` (e.g. `--unshare-net` if present). (5) Add file rules: for each BindRule, add `--ro-bind` or `--bind` source dest; ensure pipe_path parent is writable (e.g. `--bind` temp dir). (6) Add `--` then inner command from `super().subprocess_cmd(...)`. Return `(args, {})`. Set `base_url` to `http://localhost:{PORT}`. Use `__slots__` and typing override; follow project logging (logger, no f-strings in log messages).
  - Notes: Reuse helpers from firejail where useful (e.g. follow_links_executable for Python path); keep first iteration minimal (no netfilter, no AllowList). IgnoreRule can be omitted for bwrap first pass or mapped to a bind that hides paths if bwrap supports it.

- [ ] **Task 2: Register bwrap in _os_sandbox and optional deps**
  - File: `pysandboxes/_os_sandbox.py`
  - Action: Import `BWrapSSEDaemon` from `.remote.sse_bwrap_daemon`; add `"bwrap": BWrapSSEDaemon` to `providers_factory` (remove or replace the commented `# "bwrap": BWrapDaemon()`).
  - File: `pyproject.toml`
  - Action: Under `[project.optional-dependencies]` add `bwrap = []`. In the `all` list, add `bwrap` so the line reads `"pysandboxes[firejail,unshare,landlock,bubblejail,bwrap,subprocess,none]"`.

- [ ] **Task 3: Unit test for os-sandbox=bwrap**
  - File: `tests/unit_tests/test_guard_provider.py`
  - Action: Add a test (e.g. `test_os_sandbox_bwrap_valid`) that calls `parse_rules` with `ConfigLine("os-sandbox=bwrap", ...)` and asserts provider is `"bwrap"` and errors are empty. Use same mocker pattern as `test_os_sandbox_valid` (mock Path, config_path_mock, cli_path_mock).

- [ ] **Task 4: Integration test module for bwrap**
  - File: `tests/integration_tests/remote/test_bwrap.py` (new)
  - Action: Copy structure from `test_bubblejail.py`: module-scoped `event_loop`, `start_daemon_for_tests` that loads config from `Path(__file__).parent / "py-sandbox-test.profile"`, replaces `os_sandbox` with `"bwrap"` → use `"bwrap"`, starts daemon only if `which_command("bwrap")`; yield then `async_shutdown_daemon(graceful_shutdown=False)`. Two tests: `test_sync_function` and `test_async_function` (with `@sandbox()` sync/async functions), both decorated with `@pytest.mark.skipif(not which_command("bwrap"), reason="bwrap not installed")`.

- [ ] **Task 5: Add bwrap to test_usage_with_providers and container tests**
  - File: `tests/integration_tests/test_usage_with_providers.py`
  - Action: Append `"bwrap"` to `all_os_sandbox`. In `_skip_reason`, add: if `os_sandbox == "bwrap"` and not `which_command("bwrap")`, return `"bwrap not installed"`.
  - File: `tests/containers/test_containers.py`
  - Action: Add one entry to `all_os_sandbox`: `pytest.param("bwrap", True, True)` (py_sandbox True, privileged True). Document in comment that bwrap may require privileged for user namespaces in containers.

---

## Acceptance Criteria

- [ ] **AC 1**: Given a config with `os-sandbox=bwrap`, when the config is parsed by `guard_provider.parse_rules`, then the provider is `"bwrap"` and no error is added.
- [ ] **AC 2**: Given bwrap is installed and the bwrap daemon is started, when a sync function decorated with `@sandbox()` is invoked, then it runs inside the bwrap sandbox and returns the expected result.
- [ ] **AC 3**: Given bwrap is installed and the bwrap daemon is started, when an async function decorated with `@sandbox()` is invoked, then it runs inside the bwrap sandbox and returns the expected result.
- [ ] **AC 4**: Given `make unit-tests` is run, then all unit tests pass (including the new guard_provider test for bwrap).
- [ ] **AC 5**: Given `make integration-tests` is run (with bwrap installed), then integration tests pass including `test_bwrap` and `test_usage_with_provider` for `os_sandbox="bwrap"`.
- [ ] **AC 6**: Given `make container-tests` is run (with Docker or Podman and bwrap in image), then container tests pass for the bwrap parameter set (with privileged when required).

---

## Additional Context

### Dependencies

- **Runtime**: Bubblewrap (`bwrap`) must be installed on the system (e.g. `apt install bubblewrap` / `dnf install bubblewrap`). No Python package dependency; optional extra `bwrap` is for documentation only.
- **Existing**: `pysandboxes.templates.bwrap.template` and `remove_comments` / `substitute_env_vars` from `pysandboxes.tools`; `which_command`, `suggest_package_installation` from `pysandboxes.remote.tools`.

### Testing Strategy

- **Unit**: Run `make unit-tests`; ensure `test_guard_provider.py` includes bwrap valid case and no regressions.
- **Integration**: Run `make integration-tests`; with bwrap installed, `tests/integration_tests/remote/test_bwrap.py` and `test_usage_with_providers` (bwrap) must pass. Without bwrap, tests skip.
- **Container**: Run `make container-tests` (or equivalent); ensure the new bwrap parametrization passes; if the image does not include bwrap, add it to the image build or skip bwrap in container when not available (optional follow-up).

### Notes

- If the existing `bwrap.template` is insufficient to run the Python process (e.g. missing binds for stdlib), extend the template or add minimal default binds in code (e.g. `/usr`, `/etc/resolv.conf`) following the template style.
- bwrap in Docker/Podman often requires `--privileged` or at least `--cap-add=SYS_ADMIN` and user namespace support; the spec uses `privileged: True` for the container test to align with unshare. Adjust if CI shows otherwise.
