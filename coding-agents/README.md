# python-sb for coding agents

A coding agent runs Python on its own: tests, one-liners, the scripts of a skill. This directory packages two
things that make it run that Python through `python-sb`, so the rules of `.py-sandboxes` apply:

- **a skill**, [`skills/python-sb/SKILL.md`](skills/python-sb/SKILL.md): when to use `python-sb`, and what to do
  when an access is refused (report it, never widen the rules or fall back to `python`);
- **a pre-execution hook**, [`hooks/require_python_sb.py`](hooks/require_python_sb.py): it refuses a shell command
  that runs `python`, `python3`, `python3.N`, `uv run python` or `uvx python`, and tells the agent to use
  `python-sb` (or `uvx python-sb`) instead. It also refuses `python-sb --learn`, which allows every access: the
  learning mode is for the user to run, not the agent.

The script only needs the standard library. It reads the tool call on stdin, and refuses with exit code 2 and the
reason on stderr: every agent below honours that, and shows the reason to the model.

Two more skills keep the rules in step with the code:

- [`skills/pysandboxes-rules-from-tests/SKILL.md`](skills/pysandboxes-rules-from-tests/SKILL.md): when a test of a
  new feature fails on a refusal, it learns the missing rules from the feature's tests into `tests.py-sandboxes`,
  explains each one, and asks the user before granting it. The agent runs the learning only with the user's
  approval, every time: learning refuses nothing, so the feature's code then runs with no barrier other than the
  agent's own sandbox;
- [`skills/pysandboxes-review-rules/SKILL.md`](skills/pysandboxes-review-rules/SKILL.md): before a merge, it lists
  the rules a change adds to the `.py-sandboxes` files, graded by risk, and finds the code that needs each one. Its
  script, `scripts/rules_diff.py`, runs under `python-sb` with the rule file of the skill.

[`ci/sandbox-rules-review.yml`](ci/sandbox-rules-review.yml) is a GitHub workflow to copy into a project: on a pull
request that changes a `.py-sandboxes` file, it posts the graded table of the added rules. Pin the `ref` of the
pysandboxes checkout it holds to a release tag or a commit.

### AI pull-request reviewers

The workflow runs no model: its table is the same on every run. An AI reviewer can then explain each added rule,
with the code that needs it. [`ci/REVIEW_INSTRUCTIONS.md`](ci/REVIEW_INSTRUCTIONS.md) holds one paragraph for that,
the same for every reviewer; paste it into the file your reviewer reads.

| Reviewer                  | Status   | File                                                                 | Documentation                                                                                   |
|---------------------------|----------|----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| GitHub Copilot review     | untested | `.github/copilot-instructions.md`, or `AGENTS.md` at the root        | [use code review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review) |
| Codex (`@codex review`)   | untested | `AGENTS.md`, under a `## Code Review Rules` section                  | [AGENTS.md](https://developers.openai.com/codex/guides/agents-md), [GitHub](https://developers.openai.com/codex/integrations/github) |
| Claude Code Review        | untested | `REVIEW.md` at the root (`CLAUDE.md` findings are nits only)         | [code review](https://code.claude.com/docs/en/code-review)                                       |
| Claude Code GitHub Action | untested | `CLAUDE.md`                                                          | [GitHub Actions](https://code.claude.com/docs/en/github-actions)                                 |
| Gemini Code Assist        | untested | `.gemini/styleguide.md`                                              | [customize the review](https://docs.cloud.google.com/gemini/docs/code-review/customize-repo-review) |

Copilot reads the file from the branch of the pull request, so a pull request can change the instructions that
review it; the others do not say. None of the Anthropic or Google documentation mentions `AGENTS.md`.

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

## To confirm

What the documentation of each agent did not establish, and what a real run must check before the "untested"
mark goes away. For every agent, the first check is the same: ask the agent to run `python3 -c 'print(42)'`, and
verify that the command is refused and that the model receives the message of the hook.

### Claude Code

- `claude plugin validate` accepts the plugin and the marketplace; installing through
  `claude plugin marketplace add pprados/pysandboxes`, with the relative source `./coding-agents`, is not tried.
- The skill is listed and loaded by the agent.

### Codex

- The schema of `.codex-plugin/plugin.json`: only `name` and `hooks` appear in the documentation, `version` and
  `description` are assumed.
- The `skills/` directory of a plugin is discovered without a manifest entry.
- `CLAUDE_PLUGIN_ROOT` is documented as an environment variable: the shell of the hook expands
  `"${CLAUDE_PLUGIN_ROOT}"`, Codex does not substitute it.
- For `PreToolUse`, the reason of an exit code 2 reaches the model: the documentation states it for other events
  only.
- How to add this repository as a plugin source in `/plugins`.

### Gemini CLI

- The key of the shell command in `tool_input` for `run_shell_command`: the script reads `command`.
- `gemini/hooks/hooks.json` uses the shape documented for `settings.json`; the documentation of extensions does
  not show a complete file.
- `${extensionPath}` and `${/}` are substituted in the hook command, and `timeout` is in milliseconds.
- `gemini extensions link` follows the symbolic links `gemini/skills` and `gemini/hooks/require_python_sb.py`;
  `gemini extensions install` from a clone copies them or not.
- `version` is required in `gemini-extension.json`.

### Cursor

- The shape of `hooks.json` (`version`, a list of `{"command": ...}` under `beforeShellExecution`).
- The command is the top-level `command` field of the input.
- Exit code 2 refuses the command and its stderr reaches the model; otherwise the script must print
  `{"permission": "deny", "agent_message": ...}` on stdout.
- Skills: the documentation of the hooks does not mention them.

### Copilot CLI

- A `PreToolUse` entry with `"matcher": "Bash"` in `.github/hooks/*.json` fires for shell commands.
- The command is `tool_input.command` in that form (`toolArgs.command` in the `preToolUse` form, also read by the
  script).
- Exit code 2 sends its stderr to the model; the documented path for the reason is
  `{"permissionDecision": "deny", "permissionDecisionReason": ...}` on stdout.
- `.github/skills/python-sb/SKILL.md` is discovered.

## Limits

The hook is a guard against a habit, not a barrier. It reads the command line only: `sh -c "python ..."`,
`env python`, a script with a `#!/usr/bin/env python` shebang, a Makefile, `uv run --with x python` or
`uvx --python 3.12 python` (an option with a value before `python`) still run Python directly. A command it cannot parse is allowed.

Containing hostile code is the job of the OS provider of `python-sb` (`bwrap`, `landlock`, `unshare`, `qemu`),
and of `learn=false` in the rule file, which forbids the command-line options that would widen the rules. See
[Use cases](../wiki/use-cases.md).
