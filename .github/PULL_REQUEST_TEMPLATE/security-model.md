<!--
Change to a guard, `eval_*`, an OS provider or rule parsing. Target `develop`, never `master`.
A vulnerability is never fixed in a public pull request: follow SECURITY.md.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Purpose

<!-- What changes, and why. Link the issue if there is one. -->

## Layer touched

<!-- Python layer, OS layer, or both, and the provider(s) concerned. -->

## Scope

<!--
The project keeps Python code contained, it does not close every Python flaw. Say what this change contains,
and what it deliberately leaves to the OS layer or out of scope (ctypes, compiled extensions, introspection).
-->

## Checklist

- [ ] `make format` and `make validate` pass
- [ ] `make integration-tests` pass
- [ ] Default deny still holds: no default, fallback or rule widens what sandboxed code may do
- [ ] A test proves the refusal, asserted through `sandbox_denials()`, with a negative control in its own
      process, and without `OS_SANDBOX=none`
- [ ] Sandboxed code cannot widen its own permissions (rule files, learning-mode output, configuration paths)
- [ ] A new sensitive function is registered in `guard_api` under one of its categories
- [ ] The `wiki/` page of the component updated, and a new known weakness documented in `wiki/weaknesses.md`
