<!--
Target `develop`, never `master`. A vulnerability is never fixed in a public pull request: follow SECURITY.md.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Purpose

<!-- One purpose per pull request: what changes, and why. Link the issue if there is one. -->

## Layer touched

<!-- For a guard, `eval_*`, a provider or rule parsing: Python layer, OS layer, or both. Otherwise: none. -->

## Checklist

- [ ] `make format` and `make validate` pass
- [ ] `make integration-tests` pass, if a provider, the remote layer or a full workflow is touched
- [ ] Default deny still holds, and a test proves the refusal (asserted through `sandbox_denials()`, with a
      negative control)
- [ ] `README.md`, the `wiki/` page concerned or `CHANGELOG.md` updated for a user-visible change
- [ ] A new known weakness is documented in `wiki/weaknesses.md`
