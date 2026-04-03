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
* NEVER change a `.pysandboxes` configuration

Full standard is available here for further request: [Python Coding Conventions](.packmind/standards/python-coding-conventions.md)

## Standard: Python Best Practices

Advanced, production-focused rules for writing reliable, secure, observable, and maintainable Python code across services, libraries, and scripts. :
* Inject external dependencies via parameters or constructors; avoid importing globals for clients like HTTP, DB, clock, random, filesystem, and environment access.
* Make tests deterministic by controlling time, randomness, and external I/O via fakes or fixtures; avoid relying on real clocks, networks, or process environment.
* Protect shared mutable state with locks or thread-safe queues; avoid mutating globals across threads without synchronization.
* Read configuration once at startup into an immutable object; avoid reading environment variables or files throughout business logic.
* Retry only idempotent operations with bounded attempts and jittered backoff; avoid retrying non-idempotent writes or infinite loops.
* Set explicit connect and read timeouts on all network calls; avoid default timeouts or unbounded waits.
* Translate exceptions at module boundaries into typed domain errors; avoid raising raw library exceptions directly from public APIs.
* Use context managers for lifecycle-bound resources; avoid manual open/close patterns that span multiple returns or exceptions.
* Use structured logging with key/value context and exception info; avoid string-concatenated logs and swallowing stack traces.
* Validate untrusted inputs at boundaries using explicit parsing and allowlists; avoid passing raw strings into SQL, shells, file paths, or serializers.

Full standard is available here for further request: [Python Best Practices](.packmind/standards/python-best-practices.md)

## Standard: FastAPI Best Practices

Advanced, production-focused FastAPI rules for reliability, security, performance, and maintainable API behavior across typical service codebases. :
* Avoid global mutable state for request-scoped data; use request.state, dependencies, or contextvars instead of module-level dicts or caches.
* Define dependencies with yield for resources and finalize cleanup after yield; avoid creating long-lived clients or sessions per request without teardown.
* Gate retries to idempotent operations and bounded retry counts; avoid automatic retries on non-idempotent endpoints like POST without idempotency keys.
* Include correlation identifiers and structured fields in logs; avoid logging raw request bodies, authorization headers, or secrets.
* Load configuration from environment via typed settings objects; avoid importing environment variables at module import time as constants.
* Raise HTTPException with explicit status_code and detail for expected failures; avoid catching Exception and returning 200 with error payloads.
* Set explicit connect/read/write/pool timeouts on every outbound HTTP call; avoid relying on library defaults.
* Use dependency overrides in tests to swap real resources with fakes; avoid tests that call live databases, real HTTP services, or shared singletons.
* Use response_model to control output schema and hide internal fields; avoid returning ORM models or dicts containing secrets directly.
* Use run_in_threadpool for blocking I/O inside async endpoints; avoid calling synchronous database drivers or filesystem APIs directly on the event loop.

Full standard is available here for further request: [FastAPI Best Practices](.packmind/standards/fastapi-best-practices.md)
<!-- end: Packmind standards -->
