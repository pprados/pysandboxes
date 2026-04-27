# pysandboxes – Architecture

**Date:** 2026-03-12

## Executive summary

pysandboxes is a Python sandbox framework with defense-in-depth: Python-level guards (env, files, socket, import) and OS-level isolation (daemons: unshare, firejail, landlock, SSE remote). It provides a CLI (`python-sb`) and a programmatic API (`sandboxes()`, `@sandbox`, `run()`). Configuration is file-based; learning mode records violations for rule generation.

## Technology stack

- **Language:** Python 3.10–3.14
- **Package manager / build:** uv, hatchling
- **API / server:** FastAPI, uvicorn (SSE daemon)
- **Testing:** pytest, pytest-asyncio; Make: unit-tests, integration-tests, container-tests
- **Lint / format:** ruff (120), black, mypy, pyright, codespell

See [technology-stack.md](./technology-stack.md) and [architecture-patterns.md](./architecture-patterns.md).

## Architecture pattern

- **Layered:** Guards (parse_rules / patch_rules) + daemon providers (BaseDaemon, BaseSSESandbox, etc.).
- **Configuration-driven:** Rules from config files; immutable NamedTuples; learn mode with Learn* variants.
- **Dual API:** Sync and async entry points (e.g. call_in_sandbox / async_call_in_sandbox); lazy loading and proxies to avoid circular imports.

## Data architecture

- No database; in-memory rule/config and RPC structures (AllRules, ConfigLine, RPCPayload, guard NamedTuples). See [data-models-main.md](./data-models-main.md).

## API design

- **Internal SSE API:** GET /ping, POST /rpc (Bearer token); streams results via SSE. See [api-contracts-main.md](./api-contracts-main.md).
- **Public API:** sandboxes_api (sandboxes(), @sandbox, run()); python_sb CLI.

## Component overview

- **Guards:** guard_envs, guard_files, guard_import, guard_self, guard_socket (parse_rules, patch_rules).
- **Daemons:** base_daemon, remote (sse_server_daemon, sse_client_subprocess_daemon, sse_unshare_daemon, sse_firejail_daemon, landlock_daemon, none_daemon).
- **Runtime:** py_sandbox, config, all_rules, learning.

See [source-tree-analysis.md](./source-tree-analysis.md) and [component-inventory.md](./component-inventory.md).

## Development and deployment

- **Dev:** make init, make format, make lint, make unit-tests | integration-tests | container-tests, make validate. See [development-guide.md](./development-guide.md).
- **Deployment:** Container image python-sb:latest (Dockerfile; make build-image). See [deployment-guide.md](./deployment-guide.md).

## Testing strategy

- Unit tests (tests/unit_tests/), integration (tests/integration_tests/), container (tests/containers/). Pytest markers: requires, scheduled, compile. Make targets ensure .env and VIRTUAL_ENV are set correctly.
