# Architecture Patterns – pysandboxes (main)

**Date:** 2026-03-12

## Pattern

- **Style:** Service/API-centric backend with layered sandbox framework.
- **Layers:** Python-level guards (guard_*.py) + OS-level isolation (daemon providers); configuration-driven rules; lazy loading and proxies to avoid circular imports.
- **API:** FastAPI + uvicorn; async/sync unified API (e.g. call_in_sandbox / async_call_in_sandbox).
- **CLI:** Entry point python-sb for sandboxed execution; learning mode for automatic rule generation from observed behavior.
- **Testing:** pytest with markers (requires, scheduled, compile); Make targets: unit-tests, integration-tests, container-tests.
