# Use cases

`python-sb` replaces `python` on a command line. Anything started as a Python script or module can therefore be
run with a stated set of rights, and that statement is a text file that can be read, reviewed and versioned.
This page lists the situations where that is worth doing.

Two levels of protection must be kept apart, because the scenarios below do not need the same one:

- Against **legitimate code that is misused** (a tool driven by a manipulated LLM, a generated script that goes
  off the rails), the Python layer is enough: it refuses what the rules do not grant, and says so.
- Against **code written by someone hostile** (a third-party skill, a plugin, a contributor's pull request), the
  Python layer is only a guardrail: `ctypes`, compiled extensions or a shell command bypass it. A kernel provider
  (`os-sandbox=bwrap`, `landlock`, `unshare` or `qemu`, see [Choosing a provider](os-providers.md)) is then
  required, not optional.

## What the rule file does not show

Several scenarios read the `.py-sandboxes` file as the policy of a program. It is only the part that is written
down. The effective rights also depend on:

- the `include` lines: a path starting with `./` is resolved from the **current directory**, so
  `include "./.local.py-sandboxes"` lets whoever runs the command add rules. A bare name (`include "common"`)
  is resolved next to the including file. The `~/.config/...` and `/etc/...` profiles are outside the repository;
- the environment: `os-sandbox=${OS_SANDBOX:-subprocess}` lets a variable downgrade the provider;
- the command line: every `--key=value` given to `python-sb` is a rule that takes precedence over the file
  (`--learn`, `--expose-ro=/etc`, `--os-sandbox=none`), and `--pysandboxes-config=` chooses the file itself;
- the absence of the file: a missing rule file starts the **learning mode**, where the Python layer records
  accesses instead of refusing them. Deleting the file opens everything.

When the rights of a program matter, remove the `./` includes from its rule file, write `os-sandbox=` without a
variable, and add `learn=false`: the configuration is then refused if the learning mode is requested, if the rule
file is missing, or if the command line or the code adds a rule (see [Lock the rules](configuration.md#lock-the-rules)). Only
`--pysandboxes-config=` remains, so pin the full command line where the program is launched.

## Contain the script of an agent skill

An agent skill (`SKILL.md` and a `scripts/` directory, as used by Claude Code and other agents) often ships Python
scripts that the agent runs with all the rights of the user: every file of the home directory, the network, the
API tokens of the environment. Shipping a rule file next to the scripts, and launching them with `python-sb`,
bounds what a skill can do:

```text
my-skill/
├── SKILL.md
├── .py-sandboxes
└── scripts/
    └── report.py
```

```markdown
<!-- in SKILL.md -->
Run `python-sb --pysandboxes-config=<skill dir>/.py-sandboxes <skill dir>/scripts/report.py <input>`.
```

The author of the skill generates the rule file once, with `--learn` on their own machine, then reviews it and
ships it. Pin the provider, and expose the directory of the skill: otherwise the script itself is hidden, and `python` reports
`can't open file`:

```ini
# my-skill/.py-sandboxes
py-sandbox=true
os-sandbox=bwrap
expose-ro=~/.claude/skills/my-skill
python-import=codecs, csv, encodings, json
# ... the rest of what learning mode wrote
```

The rule file becomes the **permission manifest** of the skill: before installing a skill written by someone else,
read it, as one reads the permissions of a mobile application. A skill that asks for `net=ALLOW|...|OUT` or
`expose-rw=~` says so in one line. If a new version of the script tries more, the run stops at the first access
the file does not grant. A script that starts opening connections is stopped at its `import socket`:

```text
RuleModuleNotFoundError: Module named 'socket' is not allowed by a rule
```

A skill shipped without its rule file is not contained: the first run on the user's machine learns, and grants,
whatever the script does.

The instruction in `SKILL.md` is only a request: nothing stops the agent from running `python scripts/report.py`
directly. The containment holds only if the agent harness enforces it, with a permission rule that allows the
exact `python-sb` command line and refuses a bare `python` on the skill's scripts. A rule that allows any
`python-sb ...` is not enough, since the agent could point to another configuration; `learn=false` in the
skill's rule file refuses the other options, `--learn` included. The
[coding-agents](https://github.com/pprados/pysandboxes/tree/master/coding-agents) directory packages a skill and a
pre-execution hook that refuses a bare `python`, for Claude Code, Codex, Gemini CLI, Cursor and Copilot CLI.

The same reasoning applies to **hooks and plugins** of an agent written in Python: they run third-party code with
the rights of the user, and the same rule file pattern contains them.

## Limit the misuse of a tool, a CLI or an MCP server

A tool exposed to an LLM does what the LLM asks, and the LLM does what its context asks, including a prompt
injected in a web page or a document. A page fetcher can be steered towards `localhost` or the intranet, a file
reader towards `~/.ssh`, a calculator towards `os.system`. The tool's code is legitimate; its use is not.

Launch the server or the CLI under `python-sb`, so that it can only reach what its function needs, whatever it is
asked:

```bash
python-sb -m my_mcp_server
```

```ini
net=ALLOW|TCP|0.0.0.0/32|8000|IN  # The MCP endpoint
net=ALLOW|TCP|api.example.com|443|OUT
expose-ro=./data
```

See [Integrating with the MCP SDK](mcp.md) for the partial mode, where only the functions of the tools run in the
sandbox, and [Samples](samples.md) for the same two tools under twelve agent frameworks.

## Review the permissions an AI coding agent adds

An AI coding agent that hits a refused access is tempted to widen the rule file rather than question its own code.
Because `.py-sandboxes` is versioned with the code, every new right appears in the history:

```bash
git diff develop..my-branch -- '*.py-sandboxes'
git log -p -- '*.py-sandboxes'
```

The lines that deserve a human look are `learn=`, `os-sandbox=`, `include`, `expose-rw=`, outgoing `net=` rules,
`env=` and `python-api=ALLOW:`. Making a human reviewer mandatory on these files (a `CODEOWNERS` entry, a branch
protection rule) turns the diff into a gate. The diff only covers the file: see
[what the rule file does not show](#what-the-rule-file-does-not-show).

## Detect a change of behavior after a dependency update

After `uv lock --upgrade` or any version bump, run the application or its tests under `python-sb` **without**
`--learn`. A new violation means a dependency now does something it did not do before: a new host, a new file, a
new subprocess. This is a detection, not a protection: a malicious dependency installed by yourself is outside the
threat model (see [Weaknesses](weaknesses.md)). The [FAQ](faq.md#how-to-ensure-a-new-version-of-a-module-doesnt-hide-new-network-accesses)
gives the procedure.

## Run untrusted tests in CI

A pull request from a fork brings code that the CI runs, tests included. Running them with
`python-sb --pysandboxes-config=ci.py-sandboxes -m pytest` keeps the secrets of the runner out of reach, since only
the variables listed by `env=` are visible, and blocks the network except the hosts granted. This is hostile code by
definition: a kernel provider is required.

## Find out what an unknown script does

`--learn` answers the question "what does this script actually touch?": the rule file it writes lists the files,
hosts, modules, variables and sensitive calls used during the run.

```bash
python-sb --learn=audit.py-sandboxes script.py
```

In learning mode the Python layer **allows** every access while recording it. Use it on code you trust, or inside a
disposable environment (`os-sandbox=qemu`), never as a way to run a script you suspect.

## Run code an LLM generates

This is the core use case: a code interpreter tool, a data analysis agent, a calculator built on `sympy`. The
`eval-*` rules check and bound the source before it runs; see [Dynamically evaluated code](eval.md).

## Other untrusted Python

The same pattern applies to a notebook downloaded from the web, or to the plugins that each customer of a SaaS
uploads: one rule file per origin, and a kernel provider since the author is unknown.

## Limits

Only Python is covered by the Python layer. Starting a process is denied by default, but a script granted
`python-api=ALLOW:process-exec` to start `bash`, `curl` or a compiled binary escapes it, and only a kernel provider
still holds. On macOS and Windows, no kernel provider exists: the Python layer runs
alone, with `none` or `subprocess`.
