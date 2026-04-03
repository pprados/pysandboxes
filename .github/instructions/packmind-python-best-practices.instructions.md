---
applyTo: '**/*.py,**/*.pyx,**/*.pyw'
---
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

Full standard is available here for further request: [Python Best Practices](../../.packmind/standards/python-best-practices.md)