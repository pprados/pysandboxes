# AGENTS.md

This file provides guidance to coding agents working in this repository. It is generated from
`AGENTS.template.md` by `make AGENTS.md`; edit the template, not this file.

## Project Overview

PySandboxes is a Python security framework that provides sandbox environments for executing untrusted Python code safely. The project uses a multi-layered defense-in-depth security architecture combining Python API patching with an OS boundary: one provider among `none`, `subprocess`, `landlock`, `bwrap`, `firejail`, `unshare` and `qemu`. Docker and Podman are not providers of their own: a container runs the `unshare` provider, with `--privileged` for Docker.

## Development Commands

### Testing
```bash
make unit-tests              # Run unit tests
make integration-tests       # Run integration tests
make container-tests         # Run docker/podman/kubernetes tests (needs images + minikube)
make sample-tests            # Run the samples' own test suites
make all-tests               # All four of the above
make gh-tests                # Run the github action locally, through `gh act`
```

### Code Quality
```bash
make lint                    # Run all linters (mypy, pyright, black, ruff)
make format                  # Format code with black
make spell_check             # Check spell
make coverage                # Unit and integration tests with a coverage report
make pip-audit               # Audit the runtime dependencies for known CVEs
make validate                # All validation
```

### Build and Distribution
```bash
make clean                   # Clean build artifacts
make lock                    # Refresh uv.lock, which is versioned
make dist                    # Build distribution packages
make publish-pre-release VERSION=X.Y.ZbN  # Tag and push a pre-release (published to test.pypi.org by the CI)
make publish-minor           # Full local check, then tag and push the next minor final version (published to pypi.org by the CI)
make publish-patch           # Full local check, then tag and push the next patch final version (published to pypi.org by the CI)
```

## Architecture

### Core Components
- **pysandboxes/sandboxes_api.py**: Main API with `@sandbox` decorator and `sandboxes()` context manager
- **pysandboxes/py_sandbox.py**: Python-level sandbox implementation using dynamic patching
- **pysandboxes/_os_sandbox.py**: OS-level provider registry (`_PROVIDER_SPECS`), loaded lazily. Each entry
  declares the `sys.platform` values it runs on, read without importing the provider; the provider probes
  its own binaries and kernel features in `unavailable_reason()`. A macOS or Windows tag must be proven by
  `.github/workflows/cross-os.yml`, and a test module of a Linux-only provider goes in `_LINUX_ONLY_TESTS`
  (`tests/conftest.py`)
- **pysandboxes/guard_*.py**: Security guards for files (`guard_files`), network (`guard_socket`), imports
  (`guard_import`), environment (`guard_envs`), sensitive calls (`guard_api`) and dynamically evaluated
  code (`guard_eval`)
- **pysandboxes/eval_rules.py, eval_transform.py, eval_runtime.py**: the `eval-*` sub-language — parsing,
  AST rewriting and the runtime helpers that enforce what static inspection cannot
- **pysandboxes/remote/**: Server-Sent Events (SSE) based IPC for remote execution

### Security Model
- **Default deny-all** with explicit whitelisting via `.py-sandboxes` configuration files
- **Multi-layered protection**: Python API patching + an OS boundary enforced by the kernel
- **An import right is not a call right**: `guard_api` holds a registry of 121 sensitive functions in eight
  categories (`process-exec`, `process-control`, `privileges`, `threads`, `native`, `introspection`,
  `dynamic-code`, `deserialization`), denied by default and granted with `python-api=ALLOW:<category>|<function>`
- **Code arriving as a string is a layer of its own**: a source reaching `eval()`, `exec()` or `compile()` is
  parsed, checked against the sub-language described by the `eval-*` rules, rewritten, and run under a budget
  and a timeout. An emptied `__builtins__` stops nothing on its own
- **Process isolation**: Main application communicates with sandboxed child processes via SSE over local HTTP
- **Learning mode**: Automatic security rule generation based on application behavior

### Configuration
Security rules are defined in `.py-sandboxes` files using a whitelist-based system:
- Located in working directory or as package resources
- Support for environment variable substitution
- Include mechanism for configuration composition
- Learning mode for automatic rule discovery

## Key Design Patterns

- **Decorator Pattern**: Use `@sandbox` to mark functions for sandbox execution
- **Context Manager**: Use `with sandboxes():` or `async with sandboxes():` for lifecycle management
- **Dynamic Patching**: Runtime modification of Python standard library functions
- **Whitelist Security**: Everything forbidden by default, explicit permissions required

## Development Environment

- **Python**: 3.11 to 3.14 (`requires-python = ">=3.11,<3.15"`), each covered by the lint, test, sample and
  integration CI matrices; the container and API-doc workflows run on 3.13 only
- **Package Manager**: uv (exclusively — no poetry)
- **Virtual Environment**: `.venv/` directory
- **Entry Points**: `python-sb` CLI commands for sandboxed Python execution

### Branches
- **`develop`** is the integration branch: day-to-day work happens there, and feature
  branches start from it and go back to it. It is also the GitHub default branch, which
  is what lets `schedule:` and `workflow_dispatch` reach the integration workflows.
- **`master`** is for releases only. It receives a merge at publication time, never as
  part of ordinary work. Do not propose a pull request or a merge towards `master`
  outside a release, and compare a branch against `develop`, not `master`.
- **`CONTRIBUTING.md`** lists what a pull request must carry, and is the checklist the automated review
  applies. A change to those rules goes there, not only here.
- **`CHANGELOG.md`**: a merge into `develop` that brings a new feature or a user-visible fix adds one line for it to
  the open `## [0.0.0] - 202X-XX-XX` entry, under `### Added`, `### Changed` or `### Fixed`, written for users,
  without implementation detail. Never date that entry nor add a version: `make publish-patch` / `publish-minor` do.

### Design and Planning Documents
- Design specs and implementation plans live in the repository tree, in a directory git excludes, so they are
  never committed: `.superpowers/specs/YYYY-MM-DD-<topic>-design.md` and `.superpowers/plans/YYYY-MM-DD-<topic>.md`.
- This overrides any user-level rule that keeps planning files out of the repository.

## Code Quality
- Type hints required for all code
- Public APIs must have docstrings
- Functions must be focused and small
- Follow existing patterns exactly
- Line length: 120 chars maximum (`line-length` in pyproject.toml, for both ruff and black)
- Always uses 3.11 syntax (str | None in place of Optional[str])
- avoid useless comments when generating code
- For all new file, add the comment:
```python
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
```

## Testing Strategy

- **Unit Tests**: `tests/unit_tests/` - Test individual components and guards
- **Integration Tests**: `tests/integration_tests/` - Test remote execution and full workflows
- **Async Support**: pytest-asyncio for testing async functionality

## Important Notes

- The project targets AI/LLM-generated code security use cases
- Configuration files use whitelist-only security model
- Seven OS providers ship today; `none` and `subprocess` give no OS boundary at all, and the kernel-backed
  ones (`landlock`, `bwrap`, `firejail`, `unshare`, `qemu`) are what holds against compiled code
- Kernel boundaries are Linux and WSL only: every kernel-backed provider is a Linux technology. On macOS and
  Windows, the Python layer runs with `none` or `subprocess`, as `.github/workflows/cross-os.yml` proves
- Known weaknesses are documented, not hidden: see `wiki/weaknesses.md`, `wiki/audit-eval-security.md` and
  `wiki/audit-python-security.md`. `SECURITY.md` says which of them count as a vulnerability
