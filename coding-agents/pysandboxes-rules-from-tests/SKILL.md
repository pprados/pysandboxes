---
name: pysandboxes-rules-from-tests
description: Use when setting up test-based PySandboxes rule learning in an existing project, or when tests report a PySandboxes access denial and the project needs to review application, test-runner, or test-data permissions.
---

# Set up test profiles and learn application rules from pytest

## Check the PySandboxes launcher first

Before setting up profiles or running a workflow, confirm that `uvx` and the CLI work:

```bash
command -v uvx && uvx --version
uvx python-sb --help
```

If `uvx` is missing, stop and tell the user that `uvx` is installed with `uv`, and give the official installer
command for their platform. On Linux or macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Ask them to open a new terminal and rerun the checks. Do not proceed with PySandboxes CLI commands until
`uvx python-sb --help` succeeds. See the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

Use the global workflow when a project wants its full test suite to exercise the application under PySandboxes and
to discover application permissions through those tests. The existing project keeps its application profile; this
skill adds a test profile and uses a separate learning output. A pytest marker and `@sandbox` wrapper are not
required: `python-sb -m pytest` runs the entire pytest process and all code it calls under one profile.

Use the partial workflow when the application deliberately sandboxes selected functions and pytest should remain
on the host. In that mode, only calls through `@sandbox` cross the boundary; a marker can select a fixture's
profile but does not sandbox a test. If the user's request and existing code do not make the intended mode clear,
ask which mode they want before setting up profiles or running tests. Do not mix the workflows or describe a module
marker as a sandbox boundary.

## 1. Inspect the existing project

Read `.py-sandboxes`, the application entry point, test configuration, dependencies and any existing
`.py-sandboxes.tests` or `.py-sandboxes.learn`. Preserve existing rules and backups. Check for
`learn=false`; an included lock forbids learning, so stop and explain it rather than removing the lock. Fix a test
failure that indicates a code bug before learning permissions.

## 2. Set up the full-mode profiles

Explain the layout and get the user's approval before creating or changing rule files. Do not replace the existing
application profile.

`.py-sandboxes` holds only permissions the application needs outside the test suite. `.py-sandboxes.tests` composes
those rules with permissions used only by pytest, its installed plugins, or test data:

```ini
# .py-sandboxes.tests
include ".py-sandboxes"

# Reviewed test-runner, plugin and test-data rules go here.
```

`.py-sandboxes.learn` is the learning output in both modes, not an execution profile. Do not include it from either
of the other files. Let the first learning run create it. If it already exists, inspect its prior candidates and
`.old` backups; compare only the rules added by the current run and do not mistake candidates for active grants.
`.py-sandboxes.tests` is used only in full mode, where pytest runs inside the sandbox. In partial mode pytest stays
on the host, so test-runner and test-data accesses do not need a sandbox profile.

## 3. Capture test-framework permissions with an empty test

Immediately after creating `.py-sandboxes.tests`, create a temporary test containing only an empty test function,
with no imports of application modules or project dependencies. Run it in learning mode. Its purpose is to create a
framework-only baseline: the imports and accesses captured by this empty test belong to pytest and its plugins.
This baseline is what lets the later full-suite capture be compared to the framework and its permissions separated
from project test and application permissions. Do not use an existing project test as the framework baseline.
Remove the temporary test after reviewing its candidate rules.

Before the learning run, show the user the exact command and explain that learning permits accesses and does not
provide the OS sandbox boundary. Run only trusted project and test code, and proceed only after the user approves.
Write observations to the separate candidate file:

```bash
uv run --locked python-sb --pysandboxes-config=.py-sandboxes.tests \
  --learn=.py-sandboxes.learn -m pytest -q tests/test_pysandboxes_empty.py
```

The named test must contain only an empty test function. Review the resulting candidates as described below; do not
promote them automatically. Keep this candidate file as the framework baseline, remove the temporary test, then
proceed to learn from the whole suite and compare the new candidates against the baseline.

## 4. Learn from the whole suite

Before each learning run, show the user the command and explain that learning permits accesses and does not provide
the OS sandbox boundary. Run only trusted project and test code, and proceed only after the user approves that run.
The test profile is loaded; new observations are written to the separate candidate file:

```bash
uv run --locked python-sb --pysandboxes-config=.py-sandboxes.tests \
  --learn=.py-sandboxes.learn -m pytest -q
```
No `@sandbox` annotation or `pytestmark` is needed for this global run. The output is a union: pytest, plugins,
fixtures, test functions and application code share the same sandbox and learning destination. PySandboxes does
not label each rule with its source test. Compare these candidates with the empty-test baseline: rules already
observed there belong to the runner/plugins; newly observed rules come from project tests or application code and
must be classified by inspecting their callers. Existing permissions loaded from `.py-sandboxes` and
`.py-sandboxes.tests` are not learned again; the candidate file contains new accesses.

## 5. Triage candidates before granting them

For every rule in the new learning output, report risk, likely owner, confidence and code evidence. Use these
categories:

- **Application**: required by application code during the test; propose it for `.py-sandboxes`.
- **Test runner/plugin**: required to execute pytest or an installed plugin; propose it for `.py-sandboxes.tests`.
- **Test data/fixture**: needed only to load test files or fixture data; propose it for `.py-sandboxes.tests`.
- **Shared**: needed both by application runtime and tests; put it in `.py-sandboxes` only if runtime use is proven.
- **Unclear or too broad**: do not promote it; inspect the callers, narrow the rule or ask the user.

Examples: `_pytest` and `pluggy` imports are likely runner rules; a path under `tests/fixtures` is likely test data;
an import of an application module or a host contacted by its URL-reading function is likely an application rule.
For each test that exercises application code, inspect imports at both module scope and inside test functions,
fixtures and helpers. Follow imported project modules into their imports and the code paths they execute; a
dependency observed only during pytest may still be needed by the application. For example,
`test -> main -> numpy -> itertools` is evidence to check `itertools` in `.py-sandboxes`, even if learning first
observed it under `.py-sandboxes.tests`. Treat this as a lead, not an automatic promotion: imports used only by
pytest, plugins, test helpers or test data stay test-only, and transitive/dynamic imports need source evidence.
Use this standard-library-only inventory to find imports at module scope and inside tests, fixtures and helpers,
including function-local imports:

```python
import ast
from pathlib import Path

for path in sorted(Path("tests").rglob("test_*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = ", ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = f"{'.' * node.level}{node.module or ''}"
        elif isinstance(node, ast.Call) and node.args and (
            (isinstance(node.func, ast.Name) and node.func.id == "__import__")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
        ):
            names = f"dynamic import {ast.unparse(node.args[0])}"
        else:
            continue
        print(f"{path}:{node.lineno}: {names}")
```

This inventory does not resolve dynamic or transitive imports. Follow each relevant project import into the
application code and cite that actual `file:line` chain; do not install a third-party analyzer for this step.
`expose-ro=.` and broad imports are not acceptable substitutes for attribution. A rule file comment or tag such as
`# owner=pytest` is ignored by PySandboxes and cannot provide runtime provenance. Do not invent `Learned by` test
labels for global CLI output.

Use the `pysandboxes-review-rules` skill to grade candidate rules. Ask before copying accepted rules into the active
profiles. Put application rules in `.py-sandboxes`, test-only rules in `.py-sandboxes.tests`, and do not copy
unresolved candidates. `.py-sandboxes.tests` includes the app profile, so do not duplicate app rules there.

## 6. Verify both profiles strictly

Run the whole suite with the composed test profile:

```bash
uv run --locked python-sb --pysandboxes-config=.py-sandboxes.tests -m pytest -q
```

Then run the normal application entry point using only the application profile, for example:

```bash
uv run --locked python-sb --pysandboxes-config=.py-sandboxes main.py
```

A denial in either strict run means a needed rule was not accepted into that profile. A test expecting a denial
must remain strict; never learn it, since learning permits and records the access instead of refusing it.

## Partial function workflow

Use partial mode when only selected application functions are sandboxed. Launch pytest on the host; only calls
through `@sandbox` enter PySandboxes. Test code, fixtures, pytest imports and host-side test-data accesses stay out
of the learning run. The filenames and review path match full mode: `.py-sandboxes` is the application profile and
`.py-sandboxes.learn` is the candidate output. `.py-sandboxes.tests` is not needed because pytest itself stays on
the host.

Use a shared `sandboxes()` fixture. Strict runs load `.py-sandboxes`; a marked test run with `SANDBOX_LEARN=1`
loads that same profile and writes new candidates to `.py-sandboxes.learn`:

```python
PROFILE = Path(".py-sandboxes")
LEARNED = Path(".py-sandboxes.learn")

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

Mark only tests that exercise an application path through `@sandbox`; never mark tests whose purpose is to assert
a denial. Before each permissive run, show the exact command, explain that learning records accesses without the
OS sandbox boundary, and get the user's approval. Run one marked test at a time so its test identifier and the
before/after diff of `.py-sandboxes.learn` identify the source of new candidates:

```bash
SANDBOX_LEARN=1 uv run --locked pytest -p no:xdist -q tests/test_feature.py::test_feature
```

Review only the newly added candidates, following imports from the test through the decorated function and its
callers. Since pytest remains on the host, candidates from this run belong to the sandboxed application path;
promote justified runtime permissions to `.py-sandboxes` after human approval. Do not add pytest or fixture
permissions based on host-side imports. Keep candidates in `.py-sandboxes.learn` until review; do not copy the
whole file into an active profile.

For strict verification, run the whole host-side suite normally (`uv run --locked pytest -q`); decorated functions
use `.py-sandboxes`. Do not run pytest through `python-sb` in partial mode, since that would change the boundary
and learn pytest itself. Full mode instead uses `.py-sandboxes.tests` and the empty-test baseline above.
