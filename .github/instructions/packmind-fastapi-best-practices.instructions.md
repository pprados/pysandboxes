---
applyTo: '**/*.py,**/*.pyx,**/*.pyw'
---
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

Full standard is available here for further request: [FastAPI Best Practices](../../.packmind/standards/fastapi-best-practices.md)