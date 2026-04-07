# pysandboxes – Project Overview

**Date:** 2026-03-12  
**Type:** Backend / library / CLI  
**Architecture:** Layered sandbox framework (guards + OS daemons)

## Executive summary

pysandboxes adds multiple layers of security to limit application actions (e.g. for LLM-generated code or untrusted callers): Python guards (env, files, network, imports) and OS-level sandboxing (unshare, firejail, landlock, or remote SSE). Single main package with CLI (`python-sb`) and programmatic API; samples in separate directories with own uv environments.

## Project classification

- **Repository type:** Monolith
- **Project type:** backend (API, config, no DB)
- **Primary language:** Python 3.10+
- **Architecture pattern:** Service/API-centric with guard + daemon layers

## Technology stack summary

| Category | Technologies |
|----------|--------------|
| Runtime | Python 3.10–3.14, uv, hatchling |
| API | FastAPI, uvicorn, aiohttp, httpcore |
| Testing | pytest, pytest-asyncio |
| Quality | ruff, black, mypy, pyright, codespell |

## Key features

- Guards: env, files, socket, import (parse_rules / patch_rules; learn mode).
- Daemons: SSE server/client, unshare, firejail, landlock, none.
- Public API: sandboxes(), @sandbox, run(); CLI python-sb.
- Configuration-driven rules; learning mode for automatic rule generation.

## Getting started

1. `make init` then `make unit-tests` or `make validate`.
2. Run CLI: `uv run python-sb --help`.
3. See [development-guide.md](./development-guide.md) and [README.md](../README.md) in repo root.
