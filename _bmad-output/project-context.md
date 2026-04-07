---
project_name: 'pysandboxes'
user_name: 'philippe'
date: '2026-03-12'
sections_completed: ['technology_stack', 'language_specific', 'framework_specific', 'testing', 'code_quality', 'workflow', 'critical_dont_miss']
status: 'complete'
rule_count: 65
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Python**: 3.10–3.14 (`requires-python` `>=3.10,<3.15`). Use native 3.10+ typing (e.g. `X | Y`); do not use `from __future__ import annotations`.
- **Package manager**: `uv`. Use `uv run`, `uv sync`, `uv lock`; lockfile is `uv.lock`. Do not add a root `requirements.txt`; do not suggest `pip install` or Poetry for this project.
- **API**: FastAPI ≥0.115.0, uvicorn ≥0.34.0. Async: aiohttp ≥3.12.0, httpcore ≥1.0.9.
- **Tests**: pytest ≥7.3.0, pytest-asyncio, pytest-mock, pytest-dotenv. Use Make targets: `make unit-tests`, `make integration-tests`, `make container-tests`. Do not run `pytest` at project root without these targets (Makefile handles .env and VIRTUAL_ENV).
- **Lint / typing**: mypy ≥1.8, pyright, ruff ≥0.14.8 (line-length 120), black. Run format then lint.
- **Dependencies**: Add any dependency in `pyproject.toml` (section `dependencies` or `[dependency-groups]` dev/test/lint); after changes, run `uv lock`.
- **Build**: hatchling; do not replace with setuptools or flit. **CLI**: use entry points `python-sb` / `python3-sb` (or `uv run python -m pysandboxes.python_sb`) to run the project binary.
- **Tests (details)**: `make container-tests` may trigger an image build. Respect project pytest markers (`requires`, `scheduled`, `compile`) defined in `pyproject.toml`.
- **Samples**: Each sample (`samples/<name>`) has its own directory, `pyproject.toml`, and uv environment. To develop or test a sample: cd into its directory and use its `make` or activate its `.venv`.

### What agents must not do (stack & versions)

- Use Python < 3.10 syntax or `from __future__ import annotations`.
- Suggest `pip install`, Poetry, or a root `requirements.txt`.
- Run tests without the Make targets (`unit-tests`, `integration-tests`, `container-tests`).
- Run sample code from project root without being in the sample directory and its uv environment.
- Add a dependency without putting it in `pyproject.toml` and running `uv lock`.
- Change ruff line-length (keep 120) or bypass mypy/ruff.

## Critical Implementation Rules

### Language-Specific Rules (Python)

- **Typing**: Use 3.10+ syntax: `X | Y` and `X | None`, not `Union`, `Optional`, or `from __future__ import annotations`. Use built-in generics `list`, `dict`, `tuple` (not `typing.List`, etc.). Use `TypeAlias` for complex aliases.
- **Data structures**: Use immutable `NamedTuple` classes with typed fields for data models.
- **Exceptions**: Domain exceptions inherit from the project base (`SandBoxError`) and a stdlib type. Chain with `from e` when re-raising to preserve context.
- **Exception handling**: Catch specific exception types; reserve `except Exception` for background threads/daemons for cleanup. Do not swallow stack traces.
- **Logging**: Use module-level `logging.getLogger(__name__)`. Use lazy `%` formatting for messages. On exception: log at error level with `exc_info=True`.
- **Async**: Use `async def` for I/O; expose both sync and async entry points (e.g. `call_in_sandbox` and `async_call_in_sandbox`). For async operations that may block: use `asyncio.wait_for` with an explicit timeout.
- **Dependencies**: Inject external dependencies (HTTP, DB, clock, filesystem) via parameters or constructor; avoid global imports for clients.
- **Configuration**: Read configuration once at startup into an immutable object; do not read env/files in business logic.
- **Boundaries**: Validate untrusted input at boundaries (parsing, allowlists); do not pass raw strings into SQL, shell, paths, or serializers.

### Framework-Specific Rules (FastAPI / API)

- **HTTP errors**: Use `HTTPException` with explicit `status_code` and `detail` for expected failures; do not return 200 with an error body.
- **Request state**: No global mutable state for request data; use `request.state`, FastAPI dependencies, or `contextvars`.
- **Dependencies**: For resources (DB, clients), use dependencies with `yield` and perform cleanup after `yield`; avoid long-lived clients/sessions per request without teardown.
- **Response schema**: Use `response_model` to control output schema and hide internal fields; do not return ORM models or dicts containing secrets directly.
- **Blocking I/O**: In async endpoints, use `run_in_threadpool` for blocking I/O (DB, fs); do not call sync drivers directly on the event loop.
- **Outbound network**: Set explicit connect/read timeouts on all outbound HTTP calls; do not rely on library defaults.
- **Tests**: Use dependency overrides to replace real services with fakes; avoid tests that call a real DB or HTTP services.
- **Streaming (SSE)**: For streamed responses (e.g. `StreamingResponse` / SSE), handle cancellation and errors in the generator; document event format (e.g. `text/event-stream`).

### Testing Rules

- **Execution**: Use Make targets (`make unit-tests`, `make integration-tests`, `make container-tests`); Makefile handles `.env` and `VIRTUAL_ENV`. Do not run `pytest` at root without these targets.
- **Fixtures**: Prefer `autouse` fixtures in `conftest.py` for shared setup; use `scope="module"` fixtures for expensive resources (daemon, event loop).
- **Isolation**: Use `MagicMock` / `AsyncMock` to isolate dependencies; avoid manual stubs.
- **Multiple cases**: Use `pytest.mark.parametrize` for multiple cases; avoid loops or duplicated test functions.
- **Markers**: Respect markers defined in `pyproject.toml`: `requires`, `scheduled`, `compile`; do not introduce unregistered markers (`--strict-markers` is on).
- **Async**: `asyncio_mode = "auto"` is configured; async tests are handled automatically.
- **Determinism**: Make tests deterministic (control time, randomness, external I/O via fakes or fixtures); do not depend on real clock, network, or unmanaged env.
- **Samples**: To test a sample, be in its directory and use its uv env or its `make`.

### Code Quality & Style Rules

- **Order**: Run `make format` before `make lint`; the `lint` target depends on `format`.
- **Scope**: Relevant files: `pysandboxes/`, `tests/` (and `samples/` when applicable).
- **Ruff**: Line-length 120; rules E, F, B, W enabled. After format: `ruff check --select I --fix` for imports.
- **Black**: Use black for formatting; `uvx black` in check mode for lint, write mode for format.
- **Typing**: mypy with `disallow_untyped_defs = True`; pyright in basic mode. Do not leave untyped public definitions.
- **Spelling**: `make spell_check` / `spell_fix` with codespell (config in `pyproject.toml`); respect exclusions (yaml, ipynb, etc.).
- **Documentation**: Follow project conventions for docstrings and comments; see AGENTS.md for structure and coding standards.

### Development Workflow Rules

- **Validation**: `make validate` runs lock, format, lint, spell_check, and all-tests; use before considering a change ready.
- **Initialization**: `make init` runs `uv sync` (dev, test, lint groups) and any project-specific import step if configured; run after clone or dependency changes.
- **Common commands**: `make help` lists targets; `make unit-tests`, `make integration-tests`, `make container-tests` for tests; `make format`, `make lint`, `make spell_check` for quality.
- **Lockfile**: After changing deps in `pyproject.toml`, run `uv lock` (or `make lock` / as part of `make init`) then commit `uv.lock`.
- **Samples**: Each sample has its own directory and uv env; to develop or test: go to the sample directory, activate its `.venv` or use its `make` (e.g. `make tests`).
- **Release**: Release targets (publish-patch, publish-minor) assume a clean `develop` branch and explicit steps (changelog, tag, push); do not invoke without reading the Makefile.

### Critical Don't-Miss Rules

- **Guards**: `guard_*.py` modules must expose `parse_rules()` and `patch_rules(learn: bool)`; rules as `NamedTuple`; in learn mode, use `Learn*` variants that record violations instead of blocking.
- **Daemons**: Sandbox daemons extend `BaseDaemon` (or subclasses); define `__slots__`; implement `_start()`, `_stop()`, `_shutdown()` as async with exact signatures; expose `call_in_sandbox()` and `async_call_in_sandbox()`.
- **Sandbox security**: Model is defense-in-depth (Python guards + OS isolation); do not weaken guards or bypass configuration rules; validate input at boundaries.
- **Circular imports**: Use lazy loading or proxies to avoid circular imports; do not create import cycles in `pysandboxes/`.
- **Public API**: Translate exceptions at the boundary to typed domain errors (`SandBoxError`); do not let raw library exceptions leak.
- **Shared state**: Protect shared mutable state with locks or queues; do not mutate globals across threads without synchronization.
- **Network and I/O**: Always set timeouts on network calls; use `asyncio.wait_for` for async operations that may block.

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-03-12
