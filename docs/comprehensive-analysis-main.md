# Comprehensive Analysis – pysandboxes (main)

**Date:** 2026-03-12

## Config patterns

- **pyproject.toml:** Build (hatchling), deps, scripts (python-sb), pytest/mypy/ruff/codespell.
- **.env:** Used via python-dotenv (CLI/sandbox).
- Config files for guards: paths from AllRules/config; learning_path for learn mode.

## Auth / security

- **SSE daemon API:** Bearer token in `Authorization` header; token from `_os_sandbox.get_token()`.
- **Guards:** Rule-based (env, files, socket, import); learning mode records violations.

## Entry points

- **CLI:** `python-sb`, `python3-sb` → `pysandboxes.python_sb:main`.
- **Programmatic:** `sandboxes()` context manager, `@sandbox` decorator, `run()` (sandboxes_api).
- **Daemon:** SSE server (FastAPI/uvicorn) for remote execution.

## CI/CD

- **.github/workflows:** Referenced in project; CI runs tests/lint (see Makefile: validate, unit-tests, integration-tests).
