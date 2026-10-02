<!--
GitHub workflow or CI script. Target `develop`, never `master`.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Purpose

<!-- What the workflow change does, and the run that proves it (link). -->

## Checklist

- [ ] No `ref:` under `actions/checkout`; a branch is pinned through a guarded `run:` step
- [ ] A `schedule:` workflow pins or asserts the branch it tests, and never re-fetches a later commit
- [ ] Minimal `permissions:`, and no secret reachable by code coming from a fork
- [ ] `make gh-tests` runs the workflow locally through `act`, when it can
