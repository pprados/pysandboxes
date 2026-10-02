<!--
Tests only. Target `develop`, never `master`.
The requirements are in CONTRIBUTING.md, which the automated review applies.
-->

## Purpose

<!-- What the tests cover that was not covered, or the gap of wiki/tests.md they close. -->

## Checklist

- [ ] Each guard test can fail: run without the fix or the rule, it fails
- [ ] The sandbox under test is never disarmed (`OS_SANDBOX=none` in a conftest, an env file or a Makefile)
- [ ] Each blocking assertion has a negative control, run in its own process
- [ ] Refusals are asserted through `sandbox_denials()`, and `pytest.raises` stays narrow
- [ ] An escape test aims at a harmless target, and every profile it names exists on disk
- [ ] `make format` and `make validate` pass, and `make integration-tests` for integration tests
- [ ] `wiki/tests.md` updated if the coverage changes
- [ ] The tests check that sandboxed code stays contained, not that every Python flaw is closed
      (CONTRIBUTING.md, "The security model")
