## Pattern Overview

**Overall:** Layered, multi-provider sandbox framework with defense-in-depth security model.

**Key Characteristics:**
- Python-level sandboxing layer (guards) + OS-level isolation layer (providers)
- Configuration-driven rule system with pluggable daemon providers
- Lazy loading and proxy patterns for circular import avoidance
- Learning mode for automatic rule generation from observed behavior
- Async/sync unified API supporting both decorator and context manager patterns

## Main
- Use uv to manage dependencies
- Unit Test: `make unit-tests`
- Integration Test: `make integration-tests`
- More info : `make help`

## Agents
To run the agents:
```bash
cd agents
uv venv
source .venv/bin/activate
make install
make run
```

## Samples
Each sample uses a dedicated directory and uv environment.
You must navigate to it before running the sample's tests.

```bash
cd samples/mcp-client
deactivate
# Activate the specific environment
source .venv/bin/activate
make help
make tests
```
The same applies to other samples.
<!-- start: Packmind standards -->
# Packmind Standards

Before starting your work, make sure to review the coding standards relevant to your current task.

Always consult the sections that apply to the technology, framework, or type of contribution you are working on.

All rules and guidelines defined in these standards are mandatory and must be followed consistently.

Failure to follow these standards may lead to inconsistencies, errors, or rework. Treat them as the source of truth for how code should be written, structured, and maintained.

## Standard: Guard Module Pattern

Standardize guard_*.py security modules in pysandboxes/ to implement parse_rules()/patch_rules(learn: bool) interfaces using immutable NamedTuple rule classes and Learn* learning-mode variants to ensure consistent sandbox security enforcement and safe violation auditing. :
* Define rule data structures as NamedTuple classes to ensure immutability and clear field definitions
* Implement parse_rules() function that accepts configuration lines and an errors list, returning parsed rule structures
* Implement patch_rules(learn: bool) -> dict[str, Callable] function returning monkey-patches for security enforcement
* Support learning mode with dedicated Learn* rule classes that record violations instead of blocking them

Full standard is available here for further request: [Guard Module Pattern](.packmind/standards/guard-module-pattern.md)

## Standard: Daemon Lifecycle Pattern

Standardize sandbox daemon implementations by extending BaseDaemon (or BaseSSESandbox/BaseSubProcessDaemon), defining __slots__, implementing async _start()/_stop()/_shutdown() with exact signatures, and providing sync call_in_sandbox() plus async async_call_in_sandbox() to ensure consistent lifecycle management, memory efficiency, and execution semantics across sandbox providers. :
* Define __slots__ for all instance attributes to enforce memory optimization and prevent accidental attribute creation
* Extend BaseDaemon or one of its subclasses (BaseSSESandbox, BaseSubProcessDaemon) depending on execution model
* Implement all abstract lifecycle methods: _start(), _stop(), and _shutdown() as async methods with exact BaseDaemon signatures
* Provide both sync call_in_sandbox() and async async_call_in_sandbox() execution entry points

Full standard is available here for further request: [Daemon Lifecycle Pattern](.packmind/standards/daemon-lifecycle-pattern.md)

## Standard: Pytest Test Data Conventions

Standardize pytest test data construction using conftest.py autouse and module-scoped fixtures, pytest.mark.parametrize, and MagicMock/AsyncMock to ensure consistent, isolated, and efficient test coverage. :
* Use autouse fixtures in conftest.py for shared environment setup instead of repeating setup code in each test
* Use MagicMock/AsyncMock for dependency isolation instead of custom stub classes
* Use module-scoped fixtures for expensive resources like daemon startup and event loop creation
* Use pytest.mark.parametrize for multi-case testing instead of manual loops or duplicated test functions

Full standard is available here for further request: [Pytest Test Data Conventions](.packmind/standards/pytest-test-data-conventions.md)

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

Full standard is available here for further request: [Python Coding Conventions](.packmind/standards/python-coding-conventions.md)
<!-- end: Packmind standards -->
