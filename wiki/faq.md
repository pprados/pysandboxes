# FAQ

## How to display **py-sandbox** logs?
Set the level like this:
```python
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
```
This specific logger carries the main information of the component.

If you want more intimate details, use:
```python
logging.getLogger("pysandboxes").setLevel(logging.DEBUG)
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
```

## How to catch rule violation exceptions?
All rule violation exceptions are subclasses of the classic exceptions. They use multiple inheritance to be able to catch them all, regardless of their nature.

```python
from pysandboxes import SandBoxError

try:
  ...
except SandBoxError:
  ...  # Rule violated
```

> Exceptions are thrown if violations are detected by *py-sandbox* and not by *os-sandbox*.

## How to activate the sandbox in a notebook?
In on cell, you can use `with sandboxes()` or `run()`.
```python
# single cell
with sandboxes():
  ...
```

Between cells use:
```python
sb = sandboxes().__enter__()
```

## Why the current directory is used?
Sometime, with the learn process, the rule `expose-ro=.` is added. This is usually due to the presence of an `.env` file that is found by a library. This causes this directory to be added to the rules. You can set the variables manually and temporarily rename this file while the learning process is underway.

```bash
set -o allexport
source .env
set +o allexport
mv .env .env.bak
```
or
```bash
export $(grep -v '^#' .env | xargs)
```

Renaming is not always enough: `load_dotenv()` without a path searches upward from the file of the library that
calls it, and stops at the first `.env` it finds, in the project or in any of its parents. The directory holding it
then becomes an `expose-ro=` rule, a parent of the project included. With the variables exported, each name of the
file also becomes an `env=` rule: `load_dotenv()` checks whether each one is already set before it writes it. The
alternative is to disable the loading while learning, without renaming anything:

```bash
PYTHON_DOTENV_DISABLED=1 python-sb --learn=.py-sandboxes app.py
```

`PYTHON_DOTENV_DISABLED` (python-dotenv 1.2.0 or later, values `1`, `true`, `t`, `yes`, `y`) stops `load_dotenv()`
only. It does not stop `dotenv_values()`, nor a library with its own parser. What the libraries met in the samples
do:

| Library                     | Loads a `.env`                              | Disabled by                                            |
|-----------------------------|---------------------------------------------|--------------------------------------------------------|
| litellm                     | at import                                   | `PYTHON_DOTENV_DISABLED=1`, or `LITELLM_MODE` other than `DEV` |
| crewai                      | at import                                   | `PYTHON_DOTENV_DISABLED=1`                             |
| smolagents                  | at import                                   | `PYTHON_DOTENV_DISABLED=1`                             |
| google-adk                  | when the CLI loads an agent, not at import  | `ADK_DISABLE_LOAD_DOTENV=1`, or `PYTHON_DOTENV_DISABLED=1` |
| Flask                       | when the `flask` command starts             | `FLASK_SKIP_DOTENV=1`, or `PYTHON_DOTENV_DISABLED=1`   |
| pydantic-settings           | when a settings class sets `env_file`       | nothing: it reads with `dotenv_values()`               |
| mcp, fastmcp                | with `--env-file` only                      | nothing: it reads with `dotenv_values()`               |
| python-decouple             | at the first `config()` call                | nothing: it has its own parser                         |

langchain, agno, openai-agents, strands-agents, pydantic-ai and autogen load no `.env` by themselves.

## Why does learning miss an environment variable?
Learning records a variable when the code reads it, but how the code reads it decides whether an absent variable
is seen:

| Read                                      | Variable absent while learning | Variable present |
|-------------------------------------------|--------------------------------|------------------|
| `os.getenv("X")`                          | learned                        | learned          |
| `os.environ["X"]`                         | not learned (`KeyError`)       | learned          |
| `os.environ.get("X")`, `"X" in os.environ` | not learned                    | learned          |

A variable read with `os.environ.get()` and unset during learning is missing from the profile, and is then hidden
from the code once the rules apply. Export the variables the application uses before learning, as above, and
disable the loading of the `.env` so that only the variables the code reads become rules.

## How to propagate a token to an API in the sandbox?
Replace:

```python
@sandbox
def call_llm():
  ...
```
with
```python
import os
from pysandboxes import sandbox


@sandbox
def _call_llm(token: str) -> None:
    print(f"{token=}")
    ...


def call_llm() -> None:
    return _call_llm(token=os.environ["LLM_TOKEN"])
```

## How to ensure a new version of a module doesn't hide new network accesses?
Using **Py-sandboxes** also makes you aware that a module update can also call the security rules into question.
We invite you, after each update, to test your application without learning. This way, if a rule is violated, you will know its origin.
See [use cases](use-cases.md) for this scenario and the others.

##  Do I have any new rule violations since the update?
Indeed, new ones can be proposed. As the approach is based on *denial by default*, these rules are rejected. Restart a learning session to add what is necessary.
Use the minor version to fix the version to used (`n.m.*`). The minor version is incremented for each new rules.

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

## Debugging
When using an external sandbox, two processes are launched. Your development environment is normally capable of handling this, if you use `os-sandbox=subprocess`. A breakpoint in a `@sandbox` function will interrupt the program in the sandbox process. Stack trace analysis will not be easy, as there is no complete trace of the call.

If an exception is generated at this level, the stack trace will be adjusted to show the direct path, abstracting the communication layer.

### OS-sandbox debugging
To know precisely the parameters used to launch an **OS-sandbox**, and to test the behavior,
use `python-sb`.

Depending on the technologies, it may be possible to connect directly to the **os-sandbox**. For example, for firejail, use `firejail --join=firejail-sandbox`.

Consult the corresponding documentation.

### How to disable py-sandbox?
Sometimes the sandbox disrupts development. There are several approaches to disabling the sandbox while adjusting the code.

To disable only one rule family, use the generic acceptance settings.
- `env=*=${*}`
- `expose-rw=/,/`
- `net=ALLOW|*|*|*|*`
- `python-import=*`
- `python-api=ALLOW:*`
- `eval-namespace=caller`: `eval()`, `exec()` and `compile()` run the source as is, with no validation, rewrite,
  budget or timeout. `python-api=ALLOW:dynamic-code` does the same before any `eval-*` rule is read, so
  `python-api=ALLOW:*` above also lifts the `eval-*` rules
- `remote-result-mode=objects`, then `remote-result-guard=false`: the value a `@sandbox` function returns is rebuilt in
  the caller as any object, then without the denylist of dangerous classes

Or
- Use the `py-sandbox=False` parameter. This keeps the **OS-sandbox** execution with the two-process architecture, but the security rules are not activated. The Python code is not patched. Combined with `os-sandbox=subprocess`, the OS-level sandbox is not used.
- Use the `learn=.py-sandboxes` parameter. This activates learning for all launches. As soon as an alert should be triggered, it is replaced by the addition of a new rule at the end of the execution.
- Use the special `os-sandbox=none` to deactivate all the `@sandbox` annotations. The stack trace show the direct call of the functions.

## How to package the project
The `.py-sandboxes` file must be adjusted for the execution environment. Use environment variables to be able to reuse it in different contexts.
The file must also be published in the project's module directory.

The best practice it to build a wheel, with your rules.
```toml
include = [
    { include = "my-package/.py-sandboxes" }
]
```
If you want to allow rules from the working directory to be added when using your module, add the following instructions to your `my_module/.py-sandboxes` file. Then the user can change some rules.
```ini
# File my_module/.py-sandboxes
include "./.py-sandboxes"
# ... specific rules
```

## What does the sandbox cost, and what does it break?

The performance impact is negligible, and nothing breaks as long as the privilege is granted. Once an access is authorized in `.py-sandboxes`, the call behaves exactly as it would outside the sandbox: the interception adds a whitelist check, not a re-implementation. What is *not* authorized raises an explicit error, which is the whole point.

Compiled extensions are a special case: since the Python layer cannot intercept them, they are neither slowed down nor restricted by it. A database driver written in C keeps working as before, and that is exactly the gap the OS layer is there to close.
