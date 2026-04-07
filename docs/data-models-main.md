# Data Models – pysandboxes (main)

**Date:** 2026-03-12  

No traditional database or ORM; models are in-memory rule/config and RPC structures.

## RPC / API

- **RPCPayload** (dataclass, `sse_server_daemon`): `session_id`, `function`, `args`, `kwargs` (args/kwargs Base85-encoded).

## Configuration and rules

- **ConfigLine** (NamedTuple, `sb_types`): `rule`, `path`, `ln` (config line with path and line number).
- **ConfigLines**: `list[ConfigLine]`.
- **AllRules** (NamedTuple, `all_rules`): Aggregates guards and config: `root_path`, `config`, `envs`, `os_sandbox`, `os_sandbox_params`, `use_py_sandbox`, `port`, `learning_path`, `learn`, `envs_rules`, `socket_rules`, `file_rules`, `import_rules`.

## Guard rule types (per guard module)

- **guard_import:** `PatchRule`, `LearnImportRule` (NamedTuples).
- **guard_envs:** `EnvRule` (NamedTuple).
- **guard_files:** `BindRule`, `IgnoreRule`, `LearnFileRule` (NamedTuples).
- **guard_socket:** `SocketMask`, `SocketRule`, `LearnSocketRule` (NamedTuples).
- **remote (daemon):** `DaemonParameters` (NamedTuple, `sse_client_subprocess_daemon`).

## Type aliases (`sb_types`)

- **Args:** `list[str]` (CLI args).
- **Envs:** `ImmutableDict[str, str]` (environment variables).
