<!--
Bug fix outside the security model. Target `develop`, never `master`.
A vulnerability is never fixed in a public pull request: follow SECURITY.md.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Bug

<!-- What goes wrong, how to reproduce it, and the issue it closes if there is one. -->

## Fix

<!-- What changes, and why it fixes the cause rather than the symptom. -->

## Checklist

- [ ] A test reproduces the bug: it fails without the fix and passes with it
- [ ] `make format` and `make validate` pass
- [ ] `make integration-tests` pass, if a provider, the remote layer or a full workflow is touched
- [ ] `CHANGELOG.md` updated if the bug was user-visible
- [ ] The change keeps sandboxed code contained; it does not claim to close every Python flaw (CONTRIBUTING.md,
      "The security model")
