# python-sb for coding agents

A coding agent runs Python on its own: tests, one-liners, the scripts of a skill. This directory packages two
things that make it run that Python through `python-sb`, so the rules of `.py-sandboxes` apply:

- **a skill**, [`skills/python-sb/SKILL.md`](skills/python-sb/SKILL.md): when to use `python-sb`, and what to do
  when an access is refused (report it, never widen the rules or fall back to `python`);
- **a pre-execution hook**, [`hooks/require_python_sb.py`](hooks/require_python_sb.py): it refuses a shell command
  that runs `python`, `python3`, `python3.N` or `uv run python`, and tells the agent to use `python-sb` instead.

The script only needs the standard library. It reads the tool call on stdin, and refuses with exit code 2 and the
reason on stderr: every agent below honours that, and shows the reason to the model.

## Install

| Agent       | Status     | Files                                                     |
|-------------|------------|-----------------------------------------------------------|
| Claude Code | untested   | `.claude-plugin/plugin.json`, `hooks/hooks.json`, `skills/` |
| Codex       | untested   | `.codex-plugin/plugin.json`, `hooks/hooks.json`, `skills/` |
| Gemini CLI  | untested   | `gemini/`                                                 |
| Cursor      | untested   | `cursor/hooks.json` (hook only)                           |
| Copilot CLI | untested   | `copilot/python-sb.json`, `skills/`                       |

"Untested" means the files follow the documentation of the agent, but no run of the agent has checked them. The
script itself is covered by `tests/unit_tests/test_require_python_sb.py`, with the input of each agent.

### Claude Code

```bash
claude plugin marketplace add pprados/pysandboxes
claude plugin install python-sb@pysandboxes
```

### Codex

Codex reads the same `hooks/hooks.json`, and sets `CLAUDE_PLUGIN_ROOT` for compatibility. Install the plugin
from `/plugins`, then trust its hook with `/hooks`: Codex skips a plugin hook until it is trusted. Without the
plugin, copy `skills/python-sb` into `.agents/skills/` of the repository.

### Gemini CLI

Gemini installs an extension from the root of a repository only, so link this subdirectory from a clone:

```bash
gemini extensions link /path/to/pysandboxes/coding-agents/gemini
```

`gemini/skills` and `gemini/hooks/require_python_sb.py` are symbolic links to the shared files. The documentation
does not name the key of the shell command in `tool_input`; the script reads `tool_input.command`.

### Cursor

Copy `cursor/hooks.json` to `.cursor/hooks.json` (project) or `~/.cursor/hooks.json` (user), and replace
`/path/to/pysandboxes` with the path of a clone. The documentation of Cursor does not mention skills.

### Copilot CLI

Copy `copilot/python-sb.json` to `.github/hooks/` and replace `/path/to/pysandboxes`. The file uses the
`PreToolUse` form, whose payload carries `tool_input`. Copy `skills/python-sb` into `.github/skills/`.

## Limits

The hook is a guard against a habit, not a barrier. It reads the command line only: `sh -c "python ..."`,
`env python`, a script with a `#!/usr/bin/env python` shebang, a Makefile or `uv run --with x python` (an option
with a value before `python`) still run Python directly. A command it cannot parse is allowed.

Containing hostile code is the job of the OS provider of `python-sb` (`bwrap`, `landlock`, `unshare`, `qemu`),
and of `learn=false` in the rule file, which forbids the command-line options that would widen the rules. See
[Use cases](../wiki/use-cases.md).
