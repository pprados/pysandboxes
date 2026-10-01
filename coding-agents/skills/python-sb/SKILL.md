---
name: python-sb
description: Use when running Python (a script, a module, a one-liner, a skill's script) in a project that has a .py-sandboxes rule file, or when asked to run Python code that is not trusted. Runs it through python-sb, which enforces the rules of the file.
---

# Run Python through python-sb

`python-sb` is a drop-in replacement for `python`: same arguments, but the rules of the `.py-sandboxes` file of the
current directory decide which files, network destinations, imports, environment variables and sensitive functions
the code may use. Everything else is refused.

## Run

Replace `python` (or `python3`, `uv run python`) with `python-sb`, and keep the rest of the command line:

```bash
python-sb script.py arg1 arg2
python-sb -m package.module
python-sb -c "print(1)"
```

A skill that ships its own rule file names it explicitly:

```bash
python-sb --pysandboxes-config=<skill dir>/.py-sandboxes <skill dir>/scripts/report.py <input>
```

## When an access is refused

The run stops at the first access the rules do not grant, with an error such as:

```text
RuleSocketConnectionRefusedError: Guard network connection to '[1.1.1.1]:80' DENIED by implicit default policy.
```

A refusal is the rules working, not a bug to work around. Then:

1. Check whether the code needs that access at all. Often the refusal reveals a mistake (a wrong path, a stray
   network call).
2. If the access is legitimate, report the exact error to the user and propose the rule line that would grant it.
   Let the user add it.

Never, without the user's explicit request:

- run the code with `python` instead of `python-sb`;
- add `--learn`, `--py-sandbox=false`, `--os-sandbox=none` or any rule option on the command line;
- edit, delete or replace a `.py-sandboxes` file, or point `--pysandboxes-config` to another file.

A rule file with `learn=false` refuses all of these options anyway, and the error says so.

## No rule file

Without a `.py-sandboxes` file, `python-sb` runs in learning mode: it allows everything and writes the rules it
observed. Do not rely on it to contain anything; tell the user that the rules are missing.

## More

- Use cases: https://github.com/pprados/pysandboxes/blob/master/wiki/use-cases.md
- Rule syntax: https://github.com/pprados/pysandboxes/blob/master/wiki/configuration.md
