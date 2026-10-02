<!--
New option, API or behaviour outside the security model. Target `develop`, never `master`.
A change to a guard, `eval_*`, a provider or rule parsing uses security-model.md instead.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Purpose

<!-- What the feature does, who needs it, and the issue it closes if there is one. -->

## Design

<!-- How it fits the existing code: the module it extends and the pattern it follows. -->

## Checklist

- [ ] Type hints and docstrings on the new public API
- [ ] Tests cover the new behaviour
- [ ] `make format` and `make validate` pass
- [ ] `make integration-tests` pass, if a provider, the remote layer or a full workflow is touched
- [ ] `uv.lock` refreshed (`make lock`) if `pyproject.toml` changed
- [ ] `README.md`, the `wiki/` page concerned or `CHANGELOG.md` updated
- [ ] Default deny still holds: the feature grants nothing that no rule allows
- [ ] The change keeps sandboxed code contained; it does not claim to close every Python flaw (CONTRIBUTING.md,
      "The security model")
