---
name: pysandboxes-review-rules
description: Use when comparing PySandboxes rule changes before a merge, or classifying candidates from full-suite pytest learning or a targeted `@sandbox` test.
---

# Review and classify PySandboxes rules

Before running any `python-sb` command as part of verification, check that `uvx` is available and can launch the
CLI:

```bash
command -v uvx && uvx --version
uvx python-sb --help
```

If `uvx` is missing, stop and tell the user that `uvx` is installed with `uv`, and provide the official installer
for their platform. On Linux or macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Ask them to open a new terminal and rerun the checks. Do not run PySandboxes verification until
`uvx python-sb --help` succeeds. Pure diff grading with `scripts/rules_diff.py` does not invoke `python-sb` and
does not require this preflight. See the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

`.py-sandboxes` grants application permissions. In full mode, `.py-sandboxes.tests` includes it and adds test-runner
and test-data permissions. `.py-sandboxes.learn` is a candidate output in both modes, not an active profile. A full
pytest learning run mixes
runner, test, fixture and application accesses and does not identify which test caused each rule. Classify each
candidate before recommending where it belongs; never treat the learning file as an approved permission manifest.

## 1. Collect changed and learned rules

For merge review, `BASE` is the target branch and `HEAD` is the change:

```bash
git diff BASE...HEAD -- '.py-sandboxes' '.py-sandboxes.tests' '.py-sandboxes.learn' > /tmp/rules.diff
```

For learning review, compare `.py-sandboxes.learn` with the snapshot from before the run. If it is tracked, use its
working-tree diff. If it is new and untracked, make a new-file diff with:
```sh
git diff --no-index -- /dev/null .py-sandboxes.learn
```
Its exit status 1 means the expected diff exists. Feed the diff to the script below. The
script grades breadth and risk; global learning has no `Learned by` test label, so report its source as the whole
pytest run rather than inventing one.

## 2. Grade risk and determine ownership

Run the standard-library grader from this skill's directory:

```bash
cd <skill dir> && python3 scripts/rules_diff.py < /tmp/rules.diff
```

It prints added rules riskiest first and removed rules. `--json` gives the same information as a list. Risk is not
ownership: inspect the application, tests, fixtures and installed pytest plugins to justify each rule.

## 3. Find the code that needs each added rule

Read the relevant application and test code. For partial learning, use the single marked test identifier from the
command and compare `.py-sandboxes.learn` with its pre-run snapshot; the candidate file does not label individual
tests. For full-suite learning, trace likely callers from the suite and state uncertainty where the generated rule
does not identify its caller. Classify each rule as **application**, **test runner/plugin**, **test data/fixture**,
**shared**, or **unclear**. What justifies a rule:

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

Recommend destinations:

- application rules go in `.py-sandboxes`;
- pytest, plugin and fixture rules go in `.py-sandboxes.tests` in full mode. In partial mode, host-side test accesses
  stay outside the sandbox and should not be promoted;
- shared rules go in `.py-sandboxes` only if the application needs them outside tests;
- unclear and broader-than-needed rules remain ungranted until resolved.

`.py-sandboxes.tests` should include `.py-sandboxes`, not duplicate its rules. `.py-sandboxes.learn` must not be
included from either active profile. Comments such as `# owner=pytest` are ignored by the PySandboxes parser and
are not evidence of provenance. Do not copy all generated candidates into either active profile.

## 4. Report

Write the report in the user's language; only the rules stay verbatim. Group the added rules by destination file,
riskiest first. Under a heading that names the file, print each rule exactly as it appears in the profile, then,
indented on the next line, one sentence that names the code needing it: the function or module, the call that
triggers the access, and the test or entry point that exercises it. Keep a single `python-import=` line for modules
imported together. For example, for an English-speaking user:

```text
Rules added to .py-sandboxes and their origins:

  python-import=_markupbase,compression,gzip,html,io,os,re,struct,time,urllib,weakref,zlib
    Used by fetch_page_as_markdown() through gzip decompression and HTML parsing.

  python-import=web_to_markdown
    Imported by main.py for main().

  net=ALLOW|TCP|example.com|443|OUT
    fetch_page_as_markdown() calls urllib.request.urlopen(); the marked integration test and main() exercise this path.
```

Add `file:line` when the function name alone does not locate the code, the test identifier when the learning mode
supplied one, and the confidence when the owner is uncertain. A rule that is **broader than needed** or
**unexplained** says so in its origin sentence and gives the narrower rule or the removal. Name every **high** risk
rule in a sentence of its own. Then list removed rules the same way. Propose changes; do not edit an active profile
unless the user asks.

## 5. Get human approval before promotion or merge

Show the target branch and the exact rule diff, explain each proposed addition or removal, and ask the user to
approve the specific changes. Wait for an explicit answer before editing an active profile, committing rule
changes, or merging them into the target branch. Approval to learn or to change a feature does not approve rule
promotion. Immediately before a merge into the main branch, compare the branch with the current main branch again
and present the rule review, ending with a question, in the user's language, asking them to approve these rules and
the merge; do not merge until the user approves that comparison.

## Grade the diff without third-party tools

The grader reads only the diff and uses the Python standard library. Run it from the skill directory:

```bash
python3 scripts/rules_diff.py < /tmp/rules.diff
```

This review workflow does not require the `python-sb` skill or CLI.
