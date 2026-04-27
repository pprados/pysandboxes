# Technology Stack – pysandboxes (main)

**Date:** 2026-03-12

## Technology Table

| Category | Technology | Version | Justification |
|----------|-------------|---------|---------------|
| Language | Python | 3.10–3.14 | requires-python >=3.10,<3.15 |
| Package manager | uv | (lockfile) | uv.lock; no pip/poetry at root |
| Build | hatchling | - | build-system in pyproject.toml |
| API / Server | FastAPI | ≥0.115.0 | dependencies |
| ASGI server | uvicorn | ≥0.34.0 | dependencies |
| Async HTTP | aiohttp | ≥3.12.0 | dependencies |
| HTTP client | httpcore | ≥1.0.9 | dependencies |
| SSE client | aiohttp-sse-client | ≥0.2.1 | dependencies |
| Serialization | tblib | ≥3.1.0 | exception serialization |
| Networking | netifaces | ≥0.11.0 | network interfaces |
| CLI / env | python-dotenv | ≥0.9.0 | .env loading |
| Validation | email-validator | ≥2.3.0 | CLI/validation |
| DNS | dnspython | ≥2.8.0 | CLI |
| HTTP requests | requests | ≥2.32.5 | outbound calls |
| Typing | typing_extensions | ≥4.0.0 | compatibility |
| Testing | pytest | ≥7.3.0 | test runner |
| Testing | pytest-asyncio | ≥1.2.0 | async tests |
| Testing | pytest-dotenv, pytest-mock | - | env and mocks |
| Lint/format | ruff | ≥0.14.8 | line-length 120 |
| Type check | mypy | ≥1.8 | disallow_untyped_defs |
| Type check | pyright | ≥1.1 | basic mode |
| Spell | codespell | (tool) | pyproject.toml |

## Entry points

- **python-sb**, **python3-sb**, **ipython-sb**, **ipython3-sb** → `pysandboxes.python_sb:main`
