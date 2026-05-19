# Component Inventory – pysandboxes

**Date:** 2026-03-12

## Guards (security modules)

| Module | Purpose |
|--------|--------|
| guard_envs | Environment variable access rules |
| guard_files | File system expose (host↔sandbox paths) and ignore rules |
| guard_import | Python import allow/block rules |
| guard_self | Self-restriction / reflection rules |
| guard_socket | Network/socket rules (DNS, addresses) |

Each exposes `parse_rules()` and `patch_rules(learn: bool)`; rules as NamedTuples; Learn* variants in learn mode.

## Daemons (remote / OS sandbox)

| Module / class | Purpose |
|----------------|--------|
| base_daemon | BaseDaemon, FakeDaemon lifecycle |
| remote/sse_server_daemon | FastAPI SSE server (GET /ping, POST /rpc) |
| remote/sse_client_subprocess_daemon | Client for remote execution |
| remote/sse_unshare_daemon | Unshare-based OS sandbox |
| remote/sse_firejail_daemon | Firejail-based sandbox |
| remote/landlock_daemon | Landlock-based sandbox |
| remote/none_daemon | No OS sandbox |

## Core runtime

| Module | Purpose |
|--------|--------|
| sandboxes_api | Public API: sandboxes(), @sandbox, run() |
| python_sb | CLI entry (main) |
| py_sandbox | Sandbox runtime |
| config, all_rules, sb_types | Config and rule aggregation |
| learning | Learning mode (violation recording) |
