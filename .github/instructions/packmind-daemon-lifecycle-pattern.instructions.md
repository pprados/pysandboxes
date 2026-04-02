---
applyTo: 'Python files implementing sandbox daemon classes in pysandboxes/ and pysandboxes/remote/.'
---
## Standard: Daemon Lifecycle Pattern

Standardize sandbox daemon implementations by extending BaseDaemon (or BaseSSESandbox/BaseSubProcessDaemon), defining __slots__, implementing async _start()/_stop()/_shutdown() with exact signatures, and providing sync call_in_sandbox() plus async async_call_in_sandbox() to ensure consistent lifecycle management, memory efficiency, and execution semantics across sandbox providers. :
* Define __slots__ for all instance attributes to enforce memory optimization and prevent accidental attribute creation
* Extend BaseDaemon or one of its subclasses (BaseSSESandbox, BaseSubProcessDaemon) depending on execution model
* Implement all abstract lifecycle methods: _start(), _stop(), and _shutdown() as async methods with exact BaseDaemon signatures
* Provide both sync call_in_sandbox() and async async_call_in_sandbox() execution entry points

Full standard is available here for further request: [Daemon Lifecycle Pattern](../../.packmind/standards/daemon-lifecycle-pattern.md)