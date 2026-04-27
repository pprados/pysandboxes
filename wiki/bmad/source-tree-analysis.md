# pysandboxes – Source Tree Analysis

**Date:** 2026-03-12

## Overview

Single-part Python project: main package `pysandboxes/`, tests in `tests/`, samples in `samples/`, and config in `_bmad/`. Entry: CLI `python-sb` and programmatic API (`sandboxes()`, `@sandbox`).

## Directory structure (critical)

```
project-root/
├── pysandboxes/           # Main package
│   ├── remote/            # Daemons (SSE, unshare, firejail, landlock, none), task execution
│   ├── templates/          # Shell templates (bwrap, firejail, unshare, py-sandbox)
│   ├── guard_*.py         # Guards: envs, files, import, self, socket
│   ├── base_daemon.py      # Base daemon lifecycle
│   ├── sandboxes_api.py    # Public API: sandboxes(), @sandbox, run()
│   ├── python_sb.py        # CLI entry (main)
│   ├── py_sandbox.py       # Sandbox runtime
│   ├── config.py, all_rules.py, sb_types.py, e.py
│   └── ...                 # tools, learning, immutable_dict, etc.
├── tests/
│   ├── unit_tests/         # Unit (guard/, remote/)
│   ├── integration_tests/  # Integration
│   └── containers/         # Container/OS sandbox tests
├── samples/
│   ├── mcp-client-demo/    # MCP client sample (own uv env)
│   └── mcp-server-demo/    # MCP server sample (own uv env)
├── wiki/                    # Project wiki
├── pyproject.toml, Makefile, README.md, AGENTS.md
└── Dockerfile               # Container image for python-sb
```

## Critical directories

| Path | Purpose |
|------|--------|
| **pysandboxes/** | Core package: guards, daemons, sandbox runtime, public API |
| **pysandboxes/remote/** | Daemon implementations (SSE server/client, unshare, firejail, landlock) and task execution |
| **pysandboxes/templates/** | Shell templates for OS-level sandboxing |
| **tests/unit_tests/** | Unit tests (guards, remote) |
| **tests/integration_tests/** | Integration tests |
| **tests/containers/** | Container/OS sandbox tests |
| **samples/** | Standalone sample apps (each with own pyproject/uv env) |

## Entry points

- **CLI:** `python-sb` / `python3-sb` → `pysandboxes.python_sb:main`
- **API:** `sandboxes()`, `@sandbox`, `run()` in `sandboxes_api`
- **Daemon:** SSE server in `pysandboxes.remote.sse_server_daemon` (FastAPI)
