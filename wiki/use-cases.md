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
  `include "./.local.py-sandboxes"`, commented out in the template and active only once the user uncomments it,
  lets whoever runs the command add rules. A bare name (`include "common"`)
  is resolved next to the including file. The `~/.config/...` and `/etc/...` profiles are outside the repository;
- the environment: `os-sandbox=${OS_SANDBOX:-subprocess}` lets a variable downgrade the provider;
- the command line: every `--key=value` given to `python-sb` is a rule that takes precedence over the file
  (`--learn`, `--expose-ro=/etc`, `--os-sandbox=none`), and `--pysandboxes-config=` chooses the file itself;
- the absence of the file: a missing rule file starts the **learning mode**, where the Python layer records
  accesses instead of refusing them. Deleting the file opens everything.

When the rights of a program matter, remove the `./` includes from its rule file, write `os-sandbox=` without a
variable, and add `learn=false`. The configuration is then refused in three cases: the learning mode is requested,
the rule file is missing, or the command line or the code adds a rule (see [Lock the rules](configuration.md#lock-the-rules)). Only
`--pysandboxes-config=` remains, so pin the full command line where the program is launched.

## Contain the script of an agent skill

An agent skill (`SKILL.md` and a `scripts/` directory, as used by Claude Code and other agents) often ships Python
scripts. The agent runs them with all the rights of the user: every file of the home directory, the network, the
API tokens of the environment. Shipping a rule file next to the scripts, and launching them with `python-sb`,
bounds what a skill can do. For a script, `python-sb` reads the `.py-sandboxes` of the script's directory, whatever
the current directory, and falls back to `./.py-sandboxes` only when there is none:

```text
my-skill/
├── SKILL.md
└── scripts/
    ├── .py-sandboxes
    └── report.py
```

```markdown
<!-- in SKILL.md -->
Run `<skill dir>/scripts/report.py <input>`.
```

A shebang puts the `python-sb` command line in the script itself, so the agent has nothing to choose, and the line
names no path: it works wherever the skill is installed.

```python
#!/usr/bin/env -S uvx --with tabulate python-sb
# Launched by the shebang through python-sb, never by a bare `python`.
# Needs on the host: uv (for uvx). uvx fetches python-sb, pysandboxes and the third-party imports below.
# Third-party imports: tabulate (the `--with tabulate` of the shebang).
# Rules: ./.py-sandboxes, next to this script, the permission manifest of this skill.
import csv
import sys

from tabulate import tabulate
```

- Under `uvx`, the script sees only the environment of the tool: every third-party import needs its `--with`. The
  comments under the shebang say what has to be installed, so that an agent reading the script can tell the user
  before running it, rather than meeting a `ModuleNotFoundError` in the sandbox.
- `env -S` splits the line into arguments. The script needs its execute bit, and the whole first line must fit in
  the 255 bytes Linux reads.
- Until the final release reaches PyPI, put the TestPyPI options of the README's Quick start
  (`--prerelease allow --find-links ...`) in the shebang, before `python-sb`: 175 bytes for this example.

Launched through this shebang from another directory, with `os-sandbox=bwrap`, the script prints its report; a
script of the same skill that tries `import socket` is stopped by the rule file, and a `.py-sandboxes` or a
`.local.py-sandboxes` in the current directory changes nothing.

The author of the skill generates the rule file once on their own machine, then reviews it and ships it. Name the
file for learning mode, since a bare `--learn` writes into the current directory:
`python-sb --learn=<skill dir>/scripts/.py-sandboxes <skill dir>/scripts/report.py <input>`. Pin the provider, and
keep the exposed directory of the skill: otherwise the script itself is hidden, and `python` reports
`can't open file`:

```ini
# my-skill/scripts/.py-sandboxes
py-sandbox=true
os-sandbox=bwrap
learn=false
expose-ro=~/.claude/skills/my-skill/scripts
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

The user and the administrator can restrict every skill at once. A rule file written by learning mode keeps the
`include` lines of the template, among them `~/.config/py-sandboxes/user-py-sandboxes.profile` for every project of
the user, and `/etc/py-sandboxes/global-py-sandboxes.profile` for the whole node. A `net=DENY` written there wins over
any `net=ALLOW` of the skill, whatever the order, for instance to keep every skill away from the intranet:

```ini
# ~/.config/py-sandboxes/user-py-sandboxes.profile, or /etc/py-sandboxes/global-py-sandboxes.profile
net=DENY|*|10.0.0.0/8|*|OUT
net=DENY|*|172.16.0.0/12|*|OUT
net=DENY|*|192.168.0.0/16|*|OUT
```

A skill whose rule file grants `net=ALLOW|*|*|*|OUT` is then refused the intranet, and the message names the rule
that refused it:

```text
Connection to [10.255.255.1]:80 DENIED by explicit rule 'net=DENY|*|10.0.0.0/8|*|OUT' from ~/.config/py-sandboxes/user-py-sandboxes.profile(1)
```

Only `net=` works this way. A `python-api=DENY:` in these profiles wins only at equal specificity: a skill's
`python-api=ALLOW:os.system` beats a user's `python-api=DENY:process-exec`. `python-import` and `expose-*` have no
`DENY` at all.

These profiles apply only through the `include` lines: a rule file that drops them escapes them. Check that they
are still there when reading the manifest. Conversely, a skill's rule file must not uncomment the
`include "./.local.py-sandboxes"` line: that path is resolved from the current directory, not from the skill's, so a
repository the agent works in could add `python-import=socket` and `net=ALLOW|*|*|*|OUT` to the skill's rules with a
`.local.py-sandboxes` of its own.

This containment does not replace a static analysis of the skill, and the static analysis does not replace it. A
scanner such as [semgrep](https://semgrep.dev/) reads the scripts before the skill is installed, and can reject an
obvious exfiltration, but it misses what the code builds at run time (a module name in a string, an `eval`, a
dependency whose new version behaves differently) and stops nothing. `python-sb` stops at run time what the rule
file does not grant, but says nothing of what the granted rights are used for. Use both: the analysis to decide
whether to install the skill, the sandbox to bound what its scripts can do.

The instruction in `SKILL.md` is only a request: nothing stops the agent from running `python scripts/report.py`
directly. The containment holds only if the agent harness enforces it, with a permission rule that allows the
exact `python-sb` command line and refuses a bare `python` on the skill's scripts. A rule that allows any
`python-sb ...` is not enough, since the agent could point to another configuration; `learn=false` in the
skill's rule file refuses the other options, `--learn` included. The
[coding-agents](https://github.com/pprados/pysandboxes/tree/master/coding-agents) directory packages a skill and a
pre-execution hook that refuses a bare `python`, for Claude Code, Codex, Gemini CLI, Cursor and Copilot CLI.
With the shebang above, `python scripts/report.py` ignores the first line and runs without the sandbox: the hook
refuses it, which leaves `scripts/report.py`, and that goes through `python-sb`. A shebang is out of the
hook's sight, though: `scripts/report.py` runs whatever interpreter its first line names, so a skill script whose
shebang says `python3` is not contained. Read that first line when reviewing the skill.

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
