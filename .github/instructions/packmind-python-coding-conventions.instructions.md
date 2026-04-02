---
applyTo: '**/*.py'
---
## Standard: Python Coding Conventions

Standardize pysandboxes Python 3.10+ typing (pipe unions, built-in generics, TypeAlias, NamedTuple), async patterns (async def, dual sync/async entry points, asyncio.wait_for timeouts), and robust exception/logging practices (module-level logging.getLogger(__name__), lazy %-formatting, exc_info=True, specific catches, exception chaining, SandBoxError inheritance) to improve consistency, performance, and debuggability. :
* Catch specific exception types — use broad `except Exception` only in daemon/background threads for cleanup
* Chain exceptions with `from e` to preserve context when re-raising
* Define data structures as `NamedTuple` classes with typed fields
* Do not use `from __future__ import annotations` — rely on native 3.10+ syntax
* Inherit custom exceptions from both a stdlib type and the project base `SandBoxError`
* Initialize loggers at module level with `logging.getLogger(__name__)`
* Log exceptions at error level with `exc_info=True`
* Use `async def` for I/O-bound operations and provide both sync and async entry points
* Use `asyncio.wait_for` with explicit timeouts for async operations that may hang
* Use built-in generics (`list`, `dict`, `tuple`) instead of `typing.List`, `typing.Dict`, `typing.Tuple`
* Use explicit `TypeAlias` for complex type aliases and simple assignment for trivial ones
* Use lazy %-formatting for all log messages to avoid unnecessary string interpolation
* Use pipe union syntax (`X | Y`) instead of `Union[X, Y]` or `Optional[X]`

Full standard is available here for further request: [Python Coding Conventions](../../.packmind/standards/python-coding-conventions.md)