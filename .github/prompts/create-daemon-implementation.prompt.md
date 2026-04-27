---
description: 'Scaffold and register a new sandbox daemon by subclassing the appropriate Base*Daemon with proper lifecycle and sandbox call entry points to add new isolation technologies or daemon variants consistently and safely across the project.'
agent: 'agent'
---

Scaffold a new sandbox daemon following the project's daemon hierarchy: implement a **subclass of BaseDaemon** with __slots__, lifecycle methods (_start, _stop, _shutdown), and execution entry points (call_in_sandbox, async_call_in_sandbox).

## When to Use

- Adding a new sandbox isolation technology (e.g., a new container runtime, VM-based isolation)
- Creating a new daemon variant with different subprocess management or networking behavior

## Base class choice

- **BaseDaemon** : default. Use when the daemon does not need to launch a subprocess (e.g. connects to an existing server, or manages isolation without spawning a command). No need to use BaseSubProcessDaemon for that.
- **BaseSubProcessDaemon** : use only when the daemon must spawn and manage a subprocess; then override `subprocess_cmd()` to return the command and extra env.
- **BaseSSESandbox** : when the daemon is SSE-based with subprocess management.

## Context Validation Checkpoints

* [ ] Which base class should this daemon extend (BaseDaemon, BaseSSESandbox, BaseSubProcessDaemon)?
* [ ] Does this daemon launch a subprocess or connect to an external server?
* [ ] Does this daemon require custom networking (like slirp4netns in UnshareSSEDaemon)?

## Command Steps

### Step 1: Create the daemon file

Create `pysandboxes/remote/<name>_daemon.py` with a class inheriting from **BaseDaemon** (or BaseSubProcessDaemon / BaseSSESandbox only if you need subprocess launch or SSE).

```python
from typing import Any
from pysandboxes.base_daemon import BaseDaemon
from pysandboxes.all_rules import AllRules
from pysandboxes._typing import Environ, SyncOrAsyncFunc

class MyDaemon(BaseDaemon):
    __slots__ = ("my_config",)

    def __init__(self, token: str, *, my_config: str, **kwargs: Any) -> None:
        super().__init__(token, **kwargs)
        self.my_config = my_config

    async def _start(self, all_rules: AllRules, *, envs: Environ, log_level: int, init_fn: SyncOrAsyncFunc | None) -> None:
        await super()._start(all_rules, envs=envs, log_level=log_level, init_fn=init_fn)

    async def _stop(self, max_pending: int) -> None:
        await super()._stop(max_pending)

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        await super()._shutdown(graceful_shutdown)
```

### Step 2: Implement subprocess_cmd only if extending BaseSubProcessDaemon

If you chose BaseSubProcessDaemon, override `subprocess_cmd()` to return the command list and extra environment variables for launching the sandboxed subprocess. Otherwise skip this step.

### Step 3: Register the provider in os_sandbox.py

Add the new daemon to the provider registry in **pysandboxes/os_sandbox.py** (dict `providers_factory`): import the daemon class and add an entry, e.g. `"my_provider": MyDaemon`, so it can be selected via configuration.

### Step 4: Write integration tests and run container tests

Create `tests/integration_tests/remote/test_<name>.py` with module-scoped fixtures for daemon lifecycle and parametrized test cases. Run the tests with:

```bash
make container-tests
```