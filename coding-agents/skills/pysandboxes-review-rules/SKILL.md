---
name: pysandboxes-review-rules
description: Use before merging a branch or a pull request, or when asked which rights a change adds, in a project with .py-sandboxes rule files. Lists the rules the change adds to the .py-sandboxes files, graded by risk, and finds the code of the change that needs each one.
---

# Review the rights a change adds

A `.py-sandboxes` file is the permission manifest of the code it protects. A change that adds a rule grants a
right: show the user which ones, how risky each is, and which code of the change needs it, before they merge.

## 1. Collect the rule changes

`BASE` is the branch the change goes into (the target of the pull request), `HEAD` the change:

```bash
git diff BASE...HEAD -- '*.py-sandboxes*' > /tmp/rules.diff
```

## 2. Grade them

Run the script of this skill from its directory, under python-sb (see [Run python-sb](#run-python-sb)):

```bash
cd <skill dir> && python-sb --pysandboxes-config=.py-sandboxes scripts/rules_diff.py < /tmp/rules.diff
```

It prints a table of the added rules, riskiest first, and the removed ones. `--json` gives the same as a list. The
`Learned by` column names the test that learned the rule, when the rule was copied with its `# Learned by` line.

## 3. Find the code that needs each added rule

Read the code of the change, rule files excluded: `git diff BASE...HEAD -- . ':!*.py-sandboxes*'`. Start from the
test named by `Learned by` when there is one. What justifies a rule:

| Rule | Look for |
|---|---|
| `python-import=x` | `import x`, `from x import`, or a new dependency that imports `x` |
| `expose-ro=` / `expose-rw=` | a path the code reads or writes: `open()`, `Path(...)`, a configuration value |
| `net=ALLOW\|...` | a URL, a host or a port in the code or its configuration |
| `env=X=${X}` | `os.environ`, `os.getenv`, a setting read from the environment |
| `python-api=ALLOW:...` | a call of that function, or of a function of that category |
| `eval-*` | `eval()`, `exec()`, `compile()`, or a library that builds code at run time |

Give each added rule a verdict:

- **justified**: the code needs it; cite `file:line`;
- **broader than needed**: the code needs less, for example `expose-rw=~` for a single subdirectory; propose the
  narrower rule;
- **unexplained**: no code of the change needs it; propose to remove it.

A `tests.py-sandboxes` holding more than its `include` line carries learning leftovers: point them out.

## 4. Report

Show one table, riskiest first: risk, rule, verdict, code that needs it (`file:line`), test that learned it. Name
every **high** risk rule in a sentence of its own. Then list the removed rules. Propose the changes; do not edit a
`.py-sandboxes` file unless the user asks for it.

## Run python-sb

Run it without installing it, with `uvx python-sb`. Until the first final version reaches PyPI, that command fails;
then run the pre-release from TestPyPI instead:

```bash
uvx --prerelease allow --find-links https://test.pypi.org/simple/python-sb/ \
  --find-links https://test.pypi.org/simple/pysandboxes/ python-sb
```

followed by the same arguments. A project that has `python-sb` installed can run it directly.
