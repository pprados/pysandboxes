# Learning from tests

## Can the test suite feed the learning mode?
Yes, but the rules observed while tests run must be classified before they become project permissions. Keep three
roles separate:

| File | Purpose |
|---|---|
| `.py-sandboxes` | Permissions the application needs at runtime |
| `.py-sandboxes.tests` | Full mode only: the application profile plus pytest, plugin and test-data permissions |
| `.py-sandboxes.learn` | Candidate output in both modes; never include it in an active profile |

Promote only rules supported by the code path and the intended runtime. A broad test-runner rule must not become
an application permission simply because a full-suite learning run observed it. Conversely, an import used by
application code is not test-only just because a test first exercised it. Read imports at module level and inside
test functions, fixtures and helpers; follow the test into the `@sandbox` function and its application imports.
Verify the actual call path and runtime need before promoting a rule.

Learning is permissive and does not apply the OS sandbox boundary. Run only trusted code, and require a human to
review the candidates, make any needed narrow adjustments, and approve edits to active profiles. After promotion,
run the suite strictly. Before committing or merging rule changes to the main branch, compare the branch's rules
with the current target, justify each difference, and wait for human approval. The
[PySandboxes coding-agent skills](coding-agents.md) guide this review and approval workflow.

### Full mode: run pytest inside the sandbox

Use full mode when the project intends the test runner and all code it calls to run in one sandbox. Keep
`.py-sandboxes` for application rights; make `.py-sandboxes.tests` include it and add test-runner, plugin and test
data rights there. Learn into `.py-sandboxes.learn`, not into either active profile.

First learn a framework baseline with an empty test. Then learn from the full suite and compare the candidates
with that baseline. The baseline helps identify pytest and plugin accesses; inspect the remaining candidates and
their callers to distinguish application needs from test-only permissions. Global learning does not identify the
test that caused each rule, so do not invent a test attribution. Use the dedicated
[`pysandboxes-rules-from-tests` skill](../coding-agents/pysandboxes-rules-from-tests/SKILL.md) for the exact
setup and commands. Finally, run the full suite with `.py-sandboxes.tests` and the application entry point with
`.py-sandboxes` only.

### Partial mode: keep pytest on the host

In partial mode, pytest, the test function, its fixtures and assertions stay in the host pytest process. Only the
body of an `@sandbox` function and the code it calls runs in the sandbox, started by `with sandboxes()`. Therefore
pytest imports, fixture setup and host-side test data accesses are not learned. A package imported along the
application call path can still be an application permission even if the test also imports that package on the
host; inspect where the sandboxed code uses it before classifying it.

Some tests can feed the rules, never the whole suite, for three reasons:
- Running the test runner itself in the sandbox (`python-sb --learn -m pytest`) learns the runner. A test needing
  only `csv` added `_pytest`, `pluggy`, every installed pytest plugin, `subprocess`, `pdb`, `marshal`,
  `expose-rw=${TMPDIR:-/tmp}`, `expose-rw=/dev`, the `PYTEST_*` variables and
  `python-api=ALLOW:faulthandler.enable` to the profile.
- Learning never refuses, it records. A test written to provoke a refusal fails with `DID NOT RAISE`, and adds to
  the profile the very rule it was written to forbid, such as an `expose-ro` on the directory it tried to read.
- Learning forces `os-sandbox=subprocess`: the OS layer is never exercised.

### Partial mode: learn only calls through `@sandbox`

Partial mode uses the same application and candidate filenames as full mode: `.py-sandboxes` is the active
application profile and `.py-sandboxes.learn` is a temporary candidate output. Pytest stays on the host, so there
is no test-runner profile and no test-runner or host-side fixture access is learned. Full mode alone uses
`.py-sandboxes.tests` because it runs pytest inside the sandbox.

#### The partial workflow with or without coding-agent skills

The skills guide the review workflow; they do not change the sandbox boundary. In either path, pytest and test
setup stay on the host, and only calls through `@sandbox` run in PySandboxes. For multiple code changes, start each
step from the latest `master`, learn and review that step's rules, merge it, then start the next step.

| Without the skills | With the skills |
|---|---|
| Set up the `conftest.py` fixture below, keeping `.py-sandboxes` active and `.py-sandboxes.learn` separate. | Invoke `pysandboxes-rules-from-tests` to check the partial-mode setup and guide targeted learning. |
| Mark only a test that exercises the changed application path through a decorated `@sandbox` function. Learn from that test alone; pytest stays on the host. | The rules-from-tests skill also runs one marked test at a time and traces candidates through the test, decorated function and application imports. |
| Compare `.py-sandboxes.learn` before and after the run. Use code and import evidence to classify each new permission; discard runner variables, defaults, unexplained candidates and overbroad rules. | Invoke `pysandboxes-review-rules` to grade risk, classify ownership and compare active rules with the current target branch. |
| Promote only justified application permissions to `.py-sandboxes`, then run the whole suite strictly with `uv run --locked pytest -q`. | The skills propose narrow changes and verification steps; a human still reviews and approves active-rule changes. |
| Before each merge, compare the branch's rule files with the latest `master`, explain every addition or removal, and get human validation. | The review skill repeats this comparison immediately before merge and waits for human approval. |

In both paths, learning is permissive and does not provide the OS sandbox boundary. Run only trusted code. Do not
promote host-side test imports or fixture accesses: a rule belongs in `.py-sandboxes` only when the sandboxed
application path needs it. The skills do not approve permissions or merges on the human's behalf.

Add this fixture to `conftest.py`. A marked test learns only when `SANDBOX_LEARN` is set. All other tests, and all
tests without that variable, use the strict application profile. The test and its assertions remain on the host;
only the call through a decorated `@sandbox` function crosses the boundary:
```python
# conftest.py
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pysandboxes import sandboxes

PROFILE = Path(".py-sandboxes")  # paths relative to the project root, where pytest runs
LEARNED = Path(".py-sandboxes.learn")  # candidate output; not an execution profile


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "sandbox_learn: the test may feed the learned profile")


@pytest.fixture(autouse=True)
def sandbox_profile(request: pytest.FixtureRequest) -> Iterator[None]:
    learning = os.environ.get("SANDBOX_LEARN") and request.node.get_closest_marker("sandbox_learn")
    if learning:
        with sandboxes(sandboxes_config=PROFILE, learn=str(LEARNED)):
            yield
    else:
        with sandboxes(sandboxes_config=PROFILE):
            yield
```

For each feature, mark only tests that exercise the application through `@sandbox`. Never mark a test whose purpose
is to assert a denial. Keep the marker: without `SANDBOX_LEARN`, the test runs strictly.

Learn one marked test at a time. This keeps the test identifier in the command as evidence for the new candidates.
Before the run, snapshot `.py-sandboxes.learn`; learning is permissive and does not provide the OS sandbox boundary,
so get human approval before every run and execute only trusted code:
   ```bash
   SANDBOX_LEARN=1 uv run --locked pytest -p no:xdist -q tests/test_feature.py::test_export_to_csv
   ```

Compare the before/after candidate diff in `.py-sandboxes.learn`. Trace imports from the selected test through the
decorated function, application modules and their dependencies. Since the test runner remains on the host, new
candidates should come from the sandboxed application path; do not add host-side pytest or fixture permissions.
Classify, narrow and justify each rule, then get human approval before copying accepted application rules into
`.py-sandboxes`. Keep the candidate file and its backups separate from active profiles.

Run the full suite strictly after promotion:
   ```bash
   uv run --locked pytest -q
   ```
   A denial identifies a missing application rule. A test that checks a refusal and now fails with `DID NOT RAISE`
   was reopened by a promoted rule; remove it or update the test if the feature genuinely needs that access.

### Other routes
- The samples drive the application through a scenario in a `learn.py` script, run by `make learn`, and their tests
  always run strict.
- During early development, `python-import=*` in `.py-sandboxes` lets every import through, so learning records
  none. Never put it only in `.py-sandboxes.tests`: a strict application run against `.py-sandboxes` would still
  refuse unlisted imports. The learned imports need no such shortcut: the sandbox's
  own modules are never charged to the profile, so what learning lists is what the application imports, to be
  reviewed like any other rule. Before the release, remove the wildcard, relearn, review what was added. A test asserting that the shipped profile holds no `python-import=*` nor `learn=`
  keeps the wildcard from coming back, as in `samples/langchain-demo/tests/test_tools_sandbox.py`, and `learn=false`
  in the profile refuses any later request to learn.

