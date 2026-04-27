## Overview

Multi-provider sandbox: Python guards + OS providers (qemu, container, kubernetes).

All code are in english.

## Commands

```bash
make format lint          # Format + check
make unit-tests          # Unit tests
make integration-tests   # Integration tests
make container-tests     # Container tests
make gh-tests            # GitHub tests locally
make validate            # Full validation (before commit)
make help                # Show all commands
```

## Samples

Each sample have own uv environment:

```bash
cd samples/mcp-client
source .venv/bin/activate
make tests
```

## Architecture Patterns

**Guard Modules** (`guard_*.py`)
- `parse_rules(config)` → rule structures
- `patch_rules(learn: bool)` → enforcement patches
- NamedTuple rules + Learn* variants, audit violations

**Daemon Lifecycle**
- Extend BaseDaemon
- Async setup/teardown
- Config-driven, pluggable

**Test Fixtures** (`conftest.py`)
- Autouse module-scoped fixtures
- MagicMock/AsyncMock for dependencies
- `yield` for cleanup

## Python Conventions

See: `.claude/rules/python.md`

@GRAPHIFY.md
@SEMBLE.md