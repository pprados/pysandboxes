---
description: 'Scaffold a new sandbox daemon following the project''s daemon hierarchy with BaseDaemon inheritance, __slots__, lifecycle methods, and execution entry points.'
agent: 'agent'
---

Scaffold a new sandbox daemon following the project's daemon hierarchy with BaseDaemon inheritance, __slots__, lifecycle methods, and execution entry points.

## When to Use

- Adding a new sandbox isolation technology (e.g., a new container runtime, VM-based isolation)
- Creating a new daemon variant with different subprocess management or networking behavior

## Context Validation Checkpoints

* [ ] Which base class should this daemon extend (BaseDaemon, BaseSSESandbox, BaseSubProcessDaemon)?
* [ ] Does this daemon launch a subprocess or connect to an external server?
* [ ] Does this daemon require custom networking (like slirp4netns in UnshareSSEDaemon)?

## Command Steps

### Step 1: Create the daemon file

Create pysandboxes/remote/<name>_daemon.py with the class inheriting from the appropriate base.

from typing import Any
from pysandboxes.base_daemon import BaseDaemon
from pysandboxes.all_rules import AllRules
from pysandboxes._typing import Environ, SyncOrAsyncFunc

class MyDaemon(BaseSubProcessDaemon):
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

### Step 2: Implement subprocess_cmd if extending BaseSubProcessDaemon

Override subprocess_cmd() to return the command list and extra environment variables for launching the sandboxed subprocess.

### Step 3: Register the daemon as a provider

Add the new daemon to the provider registry so it can be selected via configuration (guard_provider.py).

### Step 4: Write integration tests

Create tests/integration_tests/remote/test_<name>.py with module-scoped fixtures for daemon lifecycle and parametrized test cases.
