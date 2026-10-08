## Project Overview

PySandboxes = Python security framework. Sandbox envs → run untrusted Python safe. Defense-in-depth: Python API patching + OS isolation. Python guards + 1 OS provider of `none`, `subprocess`, `landlock`, `bwrap`, `firejail`, `unshare`, `qemu`. Docker/Podman ≠ own provider: container runs `unshare` provider, `--privileged` for Docker.

All code English.

## Development Commands

### Testing
```bash
make unit-tests              # Run unit tests
make integration-tests       # Run integration tests
make container-tests         # Run docker/podman/kubernetes tests (needs images + minikube)
make sample-tests            # Run the samples' own test suites
make sample-tests-matrix     # The samples on every Python and every OS provider (before a minor or final release)
make all-tests               # All four of the above
make gh-tests                # Run the github action locally, through `gh act`
```

### Code Quality
```bash
make format                  # Format code with black
make lint                    # Run all linters (mypy, pyright, black, ruff)
make spell_check             # Check spell
make coverage                # Unit and integration tests with a coverage report
make pip-audit               # Audit the runtime dependencies for known CVEs
make validate                # All validation (before commit)
```

### Build and Distribution
```bash
make clean                   # Clean build artifacts
make lock                    # Refresh uv.lock, which is versioned
make dist                    # Build distribution packages
make publish-pre-release VERSION=X.Y.ZbN  # Tag and push a pre-release (published to test.pypi.org by the CI)
make publish-minor           # Full local check and sample-tests-matrix, then tag and push the next minor final version (published to pypi.org by the CI)
make publish-patch           # Full local check, then tag and push the next patch final version (published to pypi.org by the CI)
make publish-final VERSION=X.Y.Z  # Full local check and sample-tests-matrix, then tag and push the given final version, greater than the last (published to pypi.org by the CI)
make help                    # Show all commands
```

## Samples

Each sample = own uv env:

```bash
cd samples/mcp-client-demo
source .venv/bin/activate
make tests
```

## Architecture

### Core Components
- **pysandboxes/sandboxes_api.py**: main API. `@sandbox` decorator + `sandboxes()` ctx mgr
- **pysandboxes/py_sandbox.py**: Python-level sandbox, dynamic patching
- **pysandboxes/_os_sandbox.py**: OS provider registry (`_PROVIDER_SPECS`), lazy load. Entry declares `sys.platform` values, read w/o importing provider; provider probes own binaries + kernel features in `unavailable_reason()`. macOS/Windows tag → must be proven by `.github/workflows/cross-os.yml`. Linux-only provider test module → `_LINUX_ONLY_TESTS` (`tests/conftest.py`)
- **pysandboxes/guard_*.py**: guards: files (`guard_files`), network (`guard_socket`), imports (`guard_import`), env (`guard_envs`), sensitive calls (`guard_api`), dyn-eval code (`guard_eval`)
- **pysandboxes/eval_rules.py, eval_transform.py, eval_runtime.py**: `eval-*` sub-language. Parse, AST rewrite, runtime helpers enforce what static check can't
- **pysandboxes/remote/**: SSE IPC for remote exec, 1 daemon/provider

### Security Model
- **Default deny-all**, explicit whitelist via `.py-sandboxes` config files
- **Multi-layer**: Python API patching + kernel-enforced OS boundary
- **Import right ≠ call right**: `guard_api` registry = 121 sensitive fns, 8 categories (`process-exec`, `process-control`, `privileges`, `threads`, `native`, `introspection`, `dynamic-code`, `deserialization`). Default deny; grant w/ `python-api=ALLOW:<category>|<function>`
- **String code = own layer**: source → `eval()`/`exec()`/`compile()` → parsed, checked vs `eval-*` sub-language, rewritten, run under budget + timeout. Emptied `__builtins__` alone stops nothing
- **Process isolation**: main app ↔ sandboxed child procs via SSE over local HTTP
- **Learning mode**: auto rule gen from app behavior

### Configuration
Rules in `.py-sandboxes` files, whitelist-based:
- In working dir or as package resources
- Env var substitution
- Include mechanism → config composition
- Learning mode → auto rule discovery

## Key Design Patterns

- **Decorator**: `@sandbox` marks fns for sandbox exec
- **Context Manager**: `with sandboxes():` / `async with sandboxes():` → lifecycle
- **Dynamic Patching**: runtime mod of stdlib fns
- **Whitelist Security**: all forbidden default, explicit perms required

## Architecture Patterns

**Guard Modules** (`guard_*.py`)
- `parse_rules(config)` → rule structures
- `patch_rules(learn: bool)` → enforcement patches
- NamedTuple rules + `Learn*` variants, audit violations

**Daemon Lifecycle**
- Extend `BaseDaemon`
- Async setup/teardown
- Config-driven, pluggable

**Test Fixtures** (`conftest.py`)
- Autouse module-scoped fixtures
- MagicMock/AsyncMock for deps
- `yield` → cleanup

## Development Environment

- **Python**: 3.11–3.14 (`requires-python = ">=3.11,<3.15"`), each in lint/test/sample/integration CI matrices; container + API-doc workflows 3.13 only
- **Pkg mgr**: uv
- **Venv**: `.venv/`
- **Entry points**: `python-sb` CLI → sandboxed Python exec

### Branches
- **`develop`** = integration branch. Daily work there; feature branches from it, back to it.
- **`master`** = releases only. Merge at publication only, never ordinary work. No PR/merge → `master` outside release. Compare branch vs `develop`, not `master`.
- **`CONTRIBUTING.md`**: what PR must carry = checklist for automated review. Rule change → goes there, not only here.
- **`CHANGELOG.md`**: merge → `develop` w/ new feature or user-visible fix → add 1 line to open `## [0.0.0] - 202X-XX-XX` entry, under `### Added` / `### Changed` / `### Fixed`. User-facing, no impl detail. Post-release: no open entry; first merge after adds `## [0.0.0] - 202X-XX-XX` line + empty line, above first `## [` line. Never date entry nor add version: `make publish-patch` / `publish-minor` / `publish-final` do.

### Design and Planning Documents
- Specs + plans in repo tree, git-excluded dir, never committed: `.superpowers/specs/YYYY-MM-DD-<topic>-design.md`, `.superpowers/plans/YYYY-MM-DD-<topic>.md`.
- Overrides any user-level rule keeping planning files out of repo.

## Code Quality
- Type hints required everywhere
- Public APIs → docstrings
- Fns small, focused
- Follow existing patterns exactly
- Line length max 120 (`line-length` in pyproject.toml, ruff + black)
- Always 3.11 syntax (str | None not Optional[str])
- No useless comments in generated code
- Every new file → add:
```python
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
```

## Testing Strategy

- **Unit**: `tests/unit_tests/`: components + guards
- **Integration**: `tests/integration_tests/`: remote exec + full workflows
- **Async**: pytest-asyncio

## Important Notes

- Target: AI/LLM-generated code security
- Config files: whitelist-only model
- 7 OS providers ship. `none` + `subprocess` = no OS boundary. Kernel-backed (`landlock`, `bwrap`, `firejail`, `unshare`, `qemu`) = what holds vs compiled code
- Kernel boundaries Linux + WSL only: all kernel-backed providers = Linux tech. macOS/Windows → Python layer w/ `subprocess`, proven by `.github/workflows/cross-os.yml`
- Known weaknesses documented, not hidden: `wiki/weaknesses.md`, `wiki/audit-eval-security.md`, `wiki/audit-python-security.md`. `SECURITY.md` says which = vulnerability
