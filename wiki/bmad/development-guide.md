# Development Guide – pysandboxes

**Date:** 2026-03-12

## Prerequisites

- **Python:** 3.10–3.14 (see `requires-python` in pyproject.toml)
- **Package manager:** uv
- **Optional:** Docker or Podman for container tests; minikube for k8s-related tests

## Setup

1. Clone the repository.
2. From project root: `make init` (runs `uv sync` with dev/test/lint groups and packmind-import).
3. Optional: copy or create `.env` if needed (see README); tests load `.env` via Makefile.

## Key commands (Makefile)

| Target | Description |
|--------|-------------|
| `make help` | List all targets |
| `make init` | Install deps (uv sync), packmind-import |
| `make format` | Black + ruff import sort |
| `make lint` | mypy, pyright, black --check, ruff (after format) |
| `make spell_check` | codespell (config in pyproject.toml) |
| `make unit-tests` | pytest tests/unit_tests/ (with .env, no VIRTUAL_ENV) |
| `make integration-tests` | pytest tests/integration_tests/ |
| `make container-tests` | Build image then pytest tests/containers/ (OS_SANDBOX=unshare by default) |
| `make all-tests` | unit + integration + container + sample-tests |
| `make validate` | uv.lock, format, lint, spell_check, all-tests |
| `make dist` | Build wheel/sdist (uv build) |

## Running the CLI

- `uv run python-sb --help` or after install: `python-sb --help`
- Entry point: `pysandboxes.python_sb:main`

## Samples

Each sample has its own directory and uv environment. To develop or test a sample, `cd` into it (e.g. `samples/mcp-client`) and use its `make` or activate its `.venv` (see README and AGENTS.md).
