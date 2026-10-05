```markdown
## Project Overview

PySandboxes = Python security framework, sandbox for untrusted Python code. Defense-in-depth: Python guards (API patching) + 1 OS provider: `none`, `subprocess`, `landlock`, `bwrap`, `firejail`, `unshare`, `qemu`. Docker/Podman ≠ providers: container runs `unshare`, Docker needs `--privileged`.

All code English.

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
make publish-minor           # Full local check, then tag and push the next minor final version (published to pypi.org by the CI)
make publish-patch           # Full local check, then tag and push the next patch final version (published to pypi.org by the CI)
make help                    # Show all commands
```

## Samples

Each sample → own uv env:

```bash
cd samples/mcp-client-demo
source .venv/bin/activate
make tests
```

## Architecture

### Core Components
- `pysandboxes/sandboxes_api.py`: main API, `@sandbox` decorator + `sandboxes()` ctx mgr
- `pysandboxes/py_sandbox.py`: Python-level sandbox, dynamic patching
- `pysandboxes/_os_sandbox.py`: OS provider registry `_PROVIDER_SPECS`, lazy. Entry declares `sys.platform` values, read w/o importing provider. Provider probes own binaries/kernel features in `unavailable_reason()`. macOS/Windows tag → must be proven by `.github/workflows/cross-os.yml`. Linux-only provider test module → `_LINUX_ONLY_TESTS` (`tests/conftest.py`)
- `pysandboxes/guard_*.py`: guards: files `guard_files`, network `guard_socket`, imports `guard_import`, env `guard_envs`, sensitive calls `guard_api`, dynamic code `guard_eval`
- `pysandboxes/eval_rules.py, eval_transform.py, eval_runtime.py`: `eval-*` sub-language: parse, AST rewrite, runtime helpers for what static check can't enforce
- `pysandboxes/remote/`: SSE IPC for remote exec, 1 daemon/provider

### Security Model
- Default deny-all, whitelist via `.py-sandboxes` files
- Multi-layer: Python API patching + kernel OS boundary
- Import right ≠ call right: `guard_api` registry, 121 sensitive funcs, 8 categories (`process-exec`, `process-control`, `privileges`, `threads`, `native`, `introspection`, `dynamic-code`, `deserialization`). Denied by default, grant via `python-api=ALLOW:<category>|<function>`
- String code = own layer: source → `eval()`/`exec()`/`compile()` → parsed, checked vs `eval-*` sub-language, rewritten, run w/ budget + timeout. Empty `__builtins__` alone stops nothing
- Process isolation: main app ↔ sandboxed child via SSE over local HTTP
- Learning mode: auto rule gen from app behavior

### Configuration
Rules in `.py-sandboxes`, whitelist:
- In cwd or package resources
- Env var substitution
- Include → composition
- Learning mode → rule discovery

## Key Design Patterns

- Decorator: `@sandbox` marks func for sandbox exec
- Ctx mgr: `with sandboxes():` / `async with sandboxes():` → lifecycle
- Dynamic patching: runtime stdlib modification
- Whitelist: all forbidden by default, explicit grants

## Architecture Patterns

**Guard Modules** (`guard_*.py`)
- `parse_rules(config)` → rule structs
- `patch_rules(learn: bool)` → enforcement patches
- NamedTuple rules + `Learn*` variants, audit violations

**Daemon Lifecycle**
- Extend `BaseDaemon`
- Async setup/teardown
- Config-driven, pluggable

**Test Fixtures** (`conftest.py`)
- Autouse module-scoped
- MagicMock/AsyncMock for deps
- `yield` → cleanup

## Development Environment

- Python 3.11–3.14 (`requires-python = ">=3.11,<3.15"`), all in lint/test/sample/integration CI matrices. Container + API-doc workflows: 3.13 only
- Pkg mgr: uv only, no poetry
- Venv: `.venv/`
- Entry: `python-sb` CLI → sandboxed Python exec

### Branches
- `develop` = integration branch. Daily work there; feature branches from + back to it.
- `master` = releases only, merge at publish time only. No PR/merge → `master` outside release. Compare branch vs `develop`, not `master`.
- `CONTRIBUTING.md` = PR requirements = automated review checklist. Rule change → there, not only here.

### Design and Planning Documents
- Specs/plans in repo tree, git-excluded dir, never committed: `.superpowers/specs/YYYY-MM-DD-<topic>-design.md`, `.superpowers/plans/YYYY-MM-DD-<topic>.md`.
- Overrides user-level "no planning files in repo" rule.

## Code Quality
- Type hints everywhere
- Public APIs → docstrings
- Small focused funcs
- Follow existing patterns exactly
- Line len 120 max (`line-length` in pyproject.toml, ruff + black)
- 3.11 syntax (`str | None`, not `Optional[str]`)
- No useless comments
- New file → header:
```python
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
```

## Testing Strategy

- Unit: `tests/unit_tests/`, components + guards
- Integration: `tests/integration_tests/`, remote exec + full flows
- Async: pytest-asyncio

## Important Notes

- Target: AI/LLM-generated code security
- Config = whitelist-only
- 7 providers. `none`/`subprocess` → no OS boundary. Kernel-backed (`landlock`, `bwrap`, `firejail`, `unshare`, `qemu`) → hold vs compiled code
- Kernel boundaries Linux/WSL only. macOS/Windows → Python layer w/ `none`/`subprocess`, proven by `.github/workflows/cross-os.yml`
- Weaknesses documented: `wiki/weaknesses.md`, `wiki/audit-eval-security.md`, `wiki/audit-python-security.md`. `SECURITY.md` → which = vuln
```
