# Sandbox rules: instructions for an AI pull-request reviewer

Paste the section below into the instruction file that your reviewer reads (see the table in
[`../README.md`](../README.md#ai-pull-request-reviewers)). It is the same for every reviewer.

```markdown
## Sandbox rules review

The `.py-sandboxes` files are the security policy of this project: every rule grants the code a right that is
refused by default. On a pull request that changes a `.py-sandboxes` file:

- Read the comment of the "Sandbox rules review" workflow: it lists the added rules, riskiest first. If it is
  missing, list the added lines of the `.py-sandboxes` files yourself.
- For each added rule, find the code of the pull request that needs it, and quote it. A rule that no code of the
  pull request needs is a finding.
- Flag as a high-severity finding: `python-import=*`, `python-api=ALLOW:` on `process-exec`, `native`,
  `dynamic-code` or `deserialization`, a write right (`expose-rw`) outside the project or a temporary directory, a
  network rule open to any host or port, and a removed `learn=false` line.
- A rule must be as narrow as the code allows: a module rather than its package, a function rather than its
  category, a host and a port rather than a network.
- Never suggest widening a rule to make a test pass without naming the code that needs the right.
```
