## Overview

Sandbox. Python guard. OS box: qemu, container, kubernetes.

Code english only.

## Commands

```bash
make format lint          # Fix code, check code
make unit-tests          # Small test
make integration-tests   # Big test
make container-tests     # Box test
make gh-tests            # GitHub test, local
make validate            # All test before commit
make help                # Show commands
```

## Samples

Each sample: own uv cave.

```bash
cd samples/mcp-client
source .venv/bin/activate
make tests
```

## Patterns

**Guard** (`guard_*.py`)
- `parse_rules(config)` → make rules
- `patch_rules(learn: bool)` → enforce rules
- NamedTuple rules. Learn variants. Log bad things.

**Daemon**
- Use BaseDaemon
- Async start/stop
- Config drive it

**Test** (`conftest.py`)
- Module fixture, auto-use
- MagicMock/AsyncMock for fake things
- `yield` clean up after

## Python

See: `.claude/rules/python.md`

