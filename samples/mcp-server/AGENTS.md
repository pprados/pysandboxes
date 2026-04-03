<!-- start: Packmind standards -->
# Packmind Standards

Before starting your work, make sure to review the coding standards relevant to your current task.

Always consult the sections that apply to the technology, framework, or type of contribution you are working on.

All rules and guidelines defined in these standards are mandatory and must be followed consistently.

Failure to follow these standards may lead to inconsistencies, errors, or rework. Treat them as the source of truth for how code should be written, structured, and maintained.

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