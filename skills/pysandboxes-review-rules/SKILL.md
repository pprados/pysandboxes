---
name: pysandboxes-review-rules
description: Use when comparing PySandboxes rule changes before a merge, or classifying candidates from full-suite pytest learning or a targeted `@sandbox` test.
---

# Review PySandboxes rules

No `uvx` => ask user to run, then rerun:
- Linux, macOS: `! curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `! powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Files: `.py-sandboxes` app rules. `.py-sandboxes.tests` includes it + runner/test-data rules (full mode). `.py-sandboxes.learn` candidates only: never active, never included, never approved.
Learning has no per-test label => classify every candidate. Never invent `Learned by`.

## 1. Diff
- Merge: `git diff BASE...HEAD -- .py-sandboxes .py-sandboxes.tests .py-sandboxes.learn > /tmp/rules.diff`
- Learning: `.py-sandboxes.learn` vs pre-run snapshot. Untracked: `git diff --no-index -- /dev/null .py-sandboxes.learn` (exit 1 = ok).

## 2. Grade risk
`cd <skill dir>/scripts && "$PWD/rules_diff.py" < /tmp/rules.diff` (`--json` = list)
Windows: `cd <skill dir>/scripts; uvx python-sb "$PWD/rules_diff.py" < rules.diff`
Output: added rules riskiest first, then removed. Risk != ownership.

## 3. Classify
Read app, tests, fixtures, plugins. Partial: one marked test + diff vs snapshot. Full: trace callers, say if unsure.
Class: application | runner/plugin | test-data | shared | unclear.

| Rule | Evidence |
|---|---|
| `python-import=x` | `import x` or dependency importing it |
| `expose-ro/rw=` | `open()`, `Path()`, config path |
| `net=ALLOW\|...` | URL/host/port in code or config |
| `env=X=${X}` | `os.environ`, `os.getenv` |
| `python-api=ALLOW:...` | call of that function/category |
| `eval-*` | `eval`, `exec`, `compile`, code-building lib |

Verdict: **justified** (cite `file:line`) | **broader** (give narrower rule) | **unexplained** (remove).
Destination: application => `.py-sandboxes`. runner/plugin/test-data => `.py-sandboxes.tests` (partial mode: host-side, no promote). shared => `.py-sandboxes` only if app needs outside tests. unclear/broader => not granted.
`.py-sandboxes.tests` includes `.py-sandboxes`, no duplicates. Never include `.py-sandboxes.learn`. `# owner=` comments are not provenance. Never copy all candidates.

## 4. Report
User's language, rules verbatim. Added rules grouped by destination file, riskiest first. Each: exact rule line, indented line = function, triggering call, test/entry. Batch `python-import=` modules by destination and owner; keep each import with a criticality comment on its own line and preserve the comment. Add `file:line`, test id, confidence if needed. Broader/unexplained: say so + fix. Each **high** risk: own sentence. Then removed rules. Propose only; no active profile edit unless asked.

```text
  net=ALLOW|TCP|example.com|443|OUT
    fetch_page() calls urllib.request.urlopen(); integration test + main() exercise it.
```

## 5. Approval
Show target branch + exact diff, explain each change, ask approval per change. Explicit yes before editing active profile, committing rules, merging. Approval to learn != approval to promote. Before merge into main: re-diff vs current main, present review, ask approval of rules + merge. No yes, no merge.
