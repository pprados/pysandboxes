---
name: pysandboxes-rules-from-tests
description: Use when setting up test-based PySandboxes rule learning in an existing project, or when tests report a PySandboxes access denial and the project needs to review application, test-runner, or test-data permissions.
---

# Learn PySandboxes rules from pytest

No `uvx` => ask user to run, then rerun:
- Linux, macOS: `! curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `! powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Modes:
- **Full**: `uvx python-sb -m pytest` runs whole pytest process under one profile. No marker or `@sandbox` needed.
- **Partial**: app sandboxes selected functions (`@sandbox`), pytest stays on host. Marker only selects a fixture's profile, does not sandbox a test.
Mode unclear from request/code => ask. Never mix modes. Never call a module marker a sandbox boundary.

## Learning logs (required)
Every learning run: set `PYSANDBOXES_LOG_LEVEL=INFO` on the `python-sb` command. Keep live pytest logs at `INFO`. INFO summarizes the call stack that produced each learned rule; pytest INFO shows progress. Apply to the test-framework baseline, full-suite, and partial runs. Full mode: the variable on the command line. Partial mode: set the `Pysandboxes` logger to `INFO` before sandbox entry. Never use default logging.

## 1. Inspect
Read `.py-sandboxes`, entry point, test config, deps, existing `.py-sandboxes.tests` / `.py-sandboxes.learn`. Keep existing profile rules and backups. Learning `.old` files are disposable; remove them. `learn=false` (included lock) => stop, explain, never remove lock. Test failure from code bug => fix before learning. Run every full-mode command with the working directory at the project root (the directory containing `pyproject.toml`); never change to `tests/`. Pass test paths explicitly, such as `tests/test_pysandboxes_empty.py` or `tests`.

Never add, remove, or change a `learn=...` directive while integrating rules. Preserve any existing directive exactly; if none exists, leave it absent.

For full-mode learning, run `python-sb`, the project's test tool, and project/test dependencies in the same Python environment. Prefer the project's existing virtual environment and its `python-sb` executable when available. If using `uvx`, add the test runner and required project dependencies with `--with`; do not assume `uvx python-sb` can import them. A missing test dependency or failed collection invalidates the run and its output; retry only with a fresh output path.

## 2. Full-mode profiles
Explain layout. Learning outputs, temporary tests, and profiles may be created for learning and verification. Never replace an existing app profile. Treat every emitted learning rule as needed for the observed run. Report every rule, destination, and observed reason. Flag risky or broad rules; explain risk and why learning found them. Then ask once whether to accept all proposed rules. Do not integrate learned rules before approval. On acceptance, add all rules to their assigned profiles. On rejection, add none.
Learning run alone does not create a test-framework baseline. Create one only to bootstrap `.py-sandboxes.tests` for full-mode learning.
- `.py-sandboxes`: app rules and rich documentation.
- `.py-sandboxes.tests`: full-mode pytest execution profile; includes `.py-sandboxes` and reviewed pytest/plugin/test-data rules learned by the test-framework baseline.
- `.py-sandboxes.baseline.learn`: temporary empty-test evidence for the test-framework baseline; never an execution profile. Remove it after review and a passing strict test-framework baseline check.
- `.py-sandboxes.learn`: whole-suite delta candidates; never an execution profile or included.
- Learning keeps old candidate rules when its output file exists. Always choose a fresh, empty output path; remove any generated `.learn.old` backup after each learning command.
- Give every run a fresh output path. Create it empty before learning. Existing path => keep it; choose another. Empty files avoid the rich default template. Keep that documentation in `.py-sandboxes`.
- `.py-sandboxes.tests` only in full mode. Partial: pytest on host, no test profile needed.

Full-mode order, when bootstrapping a test profile: test-framework baseline → report all baseline rules and ask once for acceptance → add accepted rules to `.py-sandboxes.tests` → strict check of that baseline → whole-suite learning. Test-framework baseline rules come from the empty test and belong to the test runner profile. Treat all emitted candidates as needed for the observed run, including high-risk rules. Report each rule, risk, observed reason, and destination. An unseeded whole-suite profile also learns pytest and plugin imports; assign them to the test profile when evidence shows runner/plugin ownership.

```ini
# .py-sandboxes.tests
include ".py-sandboxes"

# Reviewed test-runner, plugin and test-data rules go here.
```

## 3. Test-framework baseline and test-profile bootstrap
Create one temporary test with an empty function and no app imports. Before learning, make its test directory visible in `.py-sandboxes.tests` with the narrowest read-only `expose-ro=<test-directory>` rule. PySandboxes can hide entries in unexposed directories even in learning mode; pytest may report zero tests or `not found`. Automatically add every test-framework baseline candidate to `.py-sandboxes.tests`, including broad or high-risk rules such as `expose-ro=.`. This can hide project-root reads from later learning; report that limitation and the whole-project read-access alert from section 6. Never add test-framework baseline candidates to `.py-sandboxes`. If the temporary test module is removed after strict verification, remove its import rule then; preserve the test and rule when the file pre-existed or remains part of the suite. Explain the profile layout. Whole-suite application candidates still require provenance review and explicit approval before integration.

Create the test file:

```python
# tests/test_pysandboxes_empty.py
def test_empty():
    pass
```

Pick a fresh test-framework baseline output path and create it empty. Pass the temporary test path explicitly:

```bash
touch .py-sandboxes.baseline.learn
PYSANDBOXES_LOG_LEVEL=INFO uvx --with pytest --with <project-and-test-dependencies> python-sb --pysandboxes-config=.py-sandboxes.tests --learn=.py-sandboxes.baseline.learn -c 'import pytest; raise SystemExit(pytest.main(["-q", "-o", "log_cli=true", "--log-cli-level=INFO", "tests/test_pysandboxes_empty.py"]))'
```

Prefer the project's environment when it contains `python-sb`, pytest, and all dependencies. Otherwise include pytest and project/test dependencies with `uvx --with`. Learning permits accesses and gives no OS sandbox boundary. Run trusted code only. When the task requests learning, do not ask for run approval.

Require collection and exactly `1 passed`. Zero tests, `not found`, collection errors, or test failures invalidate the test-framework baseline and its output. Stop and diagnose; retry only with a fresh output path. Keep rich documentation in `.py-sandboxes`; never seed a learn output from the template.

Review test-framework baseline candidates against an empty file and grade risks with `pysandboxes-review-rules` for reporting. Treat every emitted rule as needed for the observed baseline run, including risky imports/APIs and broad paths. List each rule, explain its observed purpose and risk, then ask once whether to accept all rules. On acceptance, add all rules to `.py-sandboxes.tests`; on rejection, add none. Exclude generated artifacts; keep a test-module import rule if that file remains in the suite. Never add these rules to `.py-sandboxes`.

Add all test-framework baseline rules to `.py-sandboxes.tests`, preserving `include ".py-sandboxes"` and avoiding duplicates. Verify the empty test in strict mode before continuing:

```bash
uvx --with pytest --with <project-and-test-dependencies> python-sb --pysandboxes-config=.py-sandboxes.tests -m pytest -q tests/test_pysandboxes_empty.py
```

Require exactly `1 passed`. If strict execution fails, diagnose the missing test-runner rule and restart test-framework baseline learning only with a fresh output path. Keep its output unchanged until strict verification passes. Never use it as the full-suite output.

After strict check passes and test-framework baseline rules are in `.py-sandboxes.tests`, remove `.py-sandboxes.baseline.learn` and `.py-sandboxes.baseline.learn.old`. Remove the empty test, its exact bytecode, and its import rule only if this workflow created them. Keep pre-existing files, rules, tests, and cache entries. Do not report test-framework baseline rules as whole-suite results.

## 4. Learn from whole suite
From the project root, create `.py-sandboxes.learn` as a new empty file after cleanup. Test-framework baseline rules must already be active through `.py-sandboxes.tests`. If the test-framework baseline includes `expose-ro=.`, keep it active for whole-suite learning and report that project-root reads are masked. Never reuse a test-framework baseline or prior learning output.

```bash
touch .py-sandboxes.learn
PYSANDBOXES_LOG_LEVEL=INFO uvx --with pytest --with <project-and-test-dependencies> python-sb --pysandboxes-config=.py-sandboxes.tests --learn=.py-sandboxes.learn -c 'import pytest; raise SystemExit(pytest.main(["-q", "-o", "log_cli=true", "--log-cli-level=INFO", "tests"]))'
```

Replace `pytest` with the project's configured test runner, include required project/test dependencies, and pass the test root explicitly when needed; or run the project's `python-sb` from its virtual environment. Verify collection and success before treating output as valid; never treat a missing import or collection failure as completed learning.

Require pytest to collect tests and report success. Failure or zero tests => stop. Diagnose with a fresh output path; never rerun into a test-framework baseline or suite output.

Because `.py-sandboxes.tests` contains accepted test-framework baseline rules, `.py-sandboxes.learn` records whole-suite accesses still missing from the active profile. Treat it as the suite delta, not a complete profile. Trace every candidate to assign its destination: app code, plugin, fixture, or test. Do not subtract the raw test-framework baseline file mechanically from `.py-sandboxes.learn`; learning records only accesses not already allowed by the active profile. Rules already in `.py-sandboxes` / `.py-sandboxes.tests` are not learned again.

### Learning log detail

Commands set `PYSANDBOXES_LOG_LEVEL=INFO` and pytest live logs to `INFO`. `python-sb` passes the level to its sandboxed process. Use a fresh learning output path each run.

INFO logs the call stack that produced each learned rule, grouped by stack. If the source stays unclear, capture stdout and stderr, then trace the operation in source.

```bash
PYSANDBOXES_LOG_LEVEL=INFO uv run --locked python-sb --pysandboxes-config=.py-sandboxes.tests --learn=.py-sandboxes.debug.learn -c 'import pytest; raise SystemExit(pytest.main(["-q", "-o", "log_cli=true", "--log-cli-level=INFO", "tests"]))'
```

Replace `tests` with the project's test root. Use a fresh output path each rerun.

## 5. Triage
For every new rule, report exact rule, risk, why learning observed it, likely owner, confidence, code evidence, and destination. Treat learning output as evidence the rule was needed for that run; provenance chooses its profile, not whether it is needed. Flag risky or broad rules plainly; never silently reject or omit a learned rule.
- **Application**: needed by app code => `.py-sandboxes`
- **Test runner/plugin**: pytest or plugin => `.py-sandboxes.tests`
- **Test data/fixture**: only loading test files/fixture data => `.py-sandboxes.tests`
- **Shared**: app runtime + tests => `.py-sandboxes` only if runtime use proven
- **Unclear/too broad**: no promotion; inspect callers, narrow rule, or report unresolved evidence

Hints: `_pytest`, `pluggy` imports = runner; path under `tests/fixtures` = test data; app module import or host of an app URL-reading function = app.
For each test exercising app code, inspect imports at module scope and inside tests, fixtures, helpers. Follow project imports into app code. Dependency seen only under pytest may still be needed by app: `test -> main -> numpy -> itertools` => check `itertools` for `.py-sandboxes`. Lead, not auto-promotion: imports used only by pytest/plugins/helpers/test data stay test-only; transitive/dynamic imports need source evidence.

Import inventory (stdlib only, finds module-scope and function-local imports):

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

Does not resolve dynamic/transitive imports: follow each relevant project import into app code, cite real `file:line` chain, no third-party analyzer. `expose-ro=.` and broad imports are not attribution. `# owner=pytest` comments ignored by PySandboxes, not provenance. Never invent `Learned by` labels for global CLI output.

Grade risks with `pysandboxes-review-rules`. Trace each whole-suite candidate through its test, imports, fixtures, helpers, and app code. For each rule, report exact rule, risk, observed reason, owner (`application`, `runner/plugin`, `test data`, `shared`, `unclear`), source (test id and `file:line` chain), confidence, and destination. Broad, risky, or unclear rules remain proposed; explain their risk and evidence. Then ask once: accept all proposed rules, or none? Do not ask per-rule approval. On acceptance, add every proposed rule to its assigned profile. On rejection, add none. Never treat approval as evidence or change a rule's risk assessment.

Approval to run learning does not approve profile changes. Report all candidates and ask once; add every candidate only if the user accepts the full set, otherwise add none. Put rules in the profile matching their owner. Never infer rules from strict denials. If strict verification needs an absent rule, report the denial and stop. Batch `python-import` modules by destination and owner; keep criticality comments on their own rule lines. Avoid duplicates; preserve existing rules. Report unresolved ownership, but still show each rule and its risk. Never copy the whole learn file into a profile without assigning destinations.

Report only new `.py-sandboxes.learn` candidates. Do not repeat test-framework baseline rules already reviewed into `.py-sandboxes.tests`. After justified test rules are added, app rules are approved, and strict verification passes, delete `.py-sandboxes.learn` and `.py-sandboxes.learn.old`. Keep only `.py-sandboxes` and `.py-sandboxes.tests` as profiles.

## 6. Verify strict
Whole suite, composed test profile:

```bash
uvx python-sb --pysandboxes-config=.py-sandboxes.tests -m pytest -q
```

App entry point, app profile only:

```bash
uvx python-sb --pysandboxes-config=.py-sandboxes main.py
```

For strict pytest verification (test-framework baseline or whole-suite), if `.py-sandboxes.tests` contains `expose-ro=.`, display: `ALERT: expose-ro=. grants read access to the entire project root, including hidden files.` Otherwise, if the only denial is `Path.cwd()` access to the project root, add that rule and display the alert. Keep it out of `.py-sandboxes`. Other denials mean a required rule is missing from that profile. Tests expecting a denial stay strict; never learn them (learning permits and records instead of refusing).

## Partial mode
Pytest on host; only `@sandbox` calls enter PySandboxes. Test code, fixtures, pytest imports, host-side test-data access stay out of learning. Same filenames and review path as full mode: `.py-sandboxes` = app profile, `.py-sandboxes.learn` = candidates. No `.py-sandboxes.tests`.

Shared `sandboxes()` fixture. Strict runs load `.py-sandboxes`; marked run with `SANDBOX_LEARN=1` loads same profile, writes candidates to `.py-sandboxes.learn`:

```python
# conftest.py
import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pysandboxes import sandboxes

PROFILE = Path(".py-sandboxes")  # paths relative to project root, where pytest runs
LEARNED = Path(".py-sandboxes.learn")  # candidate output; not an execution profile


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "sandbox_learn: the test may feed the learned profile")


@pytest.fixture(autouse=True)
def sandbox_profile(request: pytest.FixtureRequest) -> Iterator[None]:
    learning = os.environ.get("SANDBOX_LEARN") and request.node.get_closest_marker("sandbox_learn")
    if learning:
        logging.getLogger("Pysandboxes").setLevel(logging.INFO)
        with sandboxes(sandboxes_config=PROFILE, learn=str(LEARNED)):
            yield
    else:
        with sandboxes(sandboxes_config=PROFILE):
            yield
```

Mark only tests exercising an app path through `@sandbox`. Never mark tests asserting a denial. Learning records accesses without the OS sandbox boundary; run trusted code only. When the task requests learning, do not ask for run approval. Run one marked test at a time, so test id + before/after diff of `.py-sandboxes.learn` identify the source:

```bash
SANDBOX_LEARN=1 uv run --locked pytest -p no:xdist -q -o log_cli=true --log-cli-level=INFO tests/test_feature.py::test_feature
```

Review all new candidates, following imports from test through decorated function and callers. Candidates belong to the sandboxed app path (pytest on host). Treat every emitted rule as needed for the observed run. Present every rule with risk, why observed, owner, test id, `file:line` evidence, confidence, and destination. Ask once whether the user accepts all proposed rules or none. On acceptance, add all to `.py-sandboxes`; on rejection, add none. Do not promote pytest/fixture rules from host-side imports. Batch `python-import` modules by destination and owner, except modules with a criticality comment, which stay on separate lines. Keep accepted rules and remove `.py-sandboxes.learn` and `.py-sandboxes.learn.old` after strict verification.

Strict verification: whole host-side suite, `uv run --locked pytest -q`; decorated functions use `.py-sandboxes`. Never run pytest through `python-sb` in partial mode (changes boundary, learns pytest itself).
