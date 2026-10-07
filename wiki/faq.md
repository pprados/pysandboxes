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
calls it, and stops at the first `.env` it finds, in the project or in any of its parents. Each name of that file
then becomes an `env=` rule. The alternative is to disable the loading while learning, without renaming anything:

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
In partial mode, the one these tests use, the test does not run in the sandbox. pytest, the test function, its
fixtures and its assertions stay in the pytest process; only the body of each `@sandbox` function runs in a separate
process, the sandbox, started by `with sandboxes()`. Only that body is learned: what pytest imports, reads or writes
for itself never reaches the profile.

Some tests can feed the rules, never the whole suite, for three reasons:
- Running the test runner itself in the sandbox (`python-sb --learn -m pytest`) learns the runner. A test needing
  only `csv` added `_pytest`, `pluggy`, every installed pytest plugin, `subprocess`, `pdb`, `marshal`,
  `expose-rw=${TMPDIR:-/tmp}`, `expose-rw=/dev`, the `PYTEST_*` variables and
  `python-api=ALLOW:faulthandler.enable` to the profile.
- Learning never refuses, it records. A test written to provoke a refusal fails with `DID NOT RAISE`, and adds to
  the profile the very rule it was written to forbid, such as an `expose-ro` on the directory it tried to read.
- Learning forces `os-sandbox=subprocess`: the OS layer is never exercised.

### Example: a new feature and its three tests
A new feature may need new file, network or import rules, and three tests exercise it.

**Once per project**, add a `tests.py-sandboxes` file next to `.py-sandboxes`, holding a single line:
```ini
include ".py-sandboxes"
```
Learning writes there, and only there: what it adds lands below the `include`, the shipped `.py-sandboxes` is never
touched. Then add this `conftest.py`. A test marked `sandbox_learn` learns when `SANDBOX_LEARN` is set, every other
test, and every test without the variable, runs strict against `.py-sandboxes`. Each test opens its own sandbox, and
writes its name above the rules it adds:
```python
# conftest.py
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pysandboxes import sandboxes

PROFILE = Path(".py-sandboxes")  # paths relative to the project root, where pytest runs
LEARNED = Path("tests.py-sandboxes")  # `include ".py-sandboxes"`, then what learning adds


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "sandbox_learn: the test may feed the learned profile")


@pytest.fixture(autouse=True)
def sandbox_profile(request: pytest.FixtureRequest) -> Iterator[None]:
    if os.environ.get("SANDBOX_LEARN") and request.node.get_closest_marker("sandbox_learn"):
        before = LEARNED.read_text()
        tagged = f"{before.rstrip()}\n\n# Learned by {request.node.nodeid}\n"
        LEARNED.write_text(tagged)  # learning appends its rules below this line
        with sandboxes(sandboxes_config=LEARNED, learn=str(LEARNED)):
            yield
        if LEARNED.read_text() == tagged:  # the test needed nothing new
            LEARNED.write_text(before)
    else:
        with sandboxes(sandboxes_config=PROFILE):
            yield
```

**For the feature:**
1. Mark the three tests with `@pytest.mark.sandbox_learn`, provided each one exercises the feature as it should
   work. A test that checks a refusal is never marked. The marks can stay: without `SANDBOX_LEARN`, they do nothing.
2. Learn, serially, since each sandbox rewrites `tests.py-sandboxes` when it closes. `-p no:xdist` turns off
   pytest-xdist's parallel workers, and is accepted whether or not the plugin is installed:
   ```bash
   SANDBOX_LEARN=1 pytest -p no:xdist -m sandbox_learn
   ```
3. Read `tests.py-sandboxes`: below the `include` are exactly the rules the feature needed, each block under the name
   of the test that asked for it. A rule two tests need is credited to the first, the second finding it allowed:
   ```ini
   include ".py-sandboxes"

   # Learned by tests/test_feature.py::test_export_to_csv

   # Add rules (2026/10/07 at 14:00)
   # Standard Python
   python-import=_csv, csv
   ```
   Copy into `.py-sandboxes` those you accept, then put `tests.py-sandboxes` back to its single `include` line and
   delete the `tests.old*` backups learning left beside it.
4. Run the whole suite strict:
   ```bash
   pytest
   ```
   A feature test that fails is missing a rule you did not copy. A test that checks a refusal and now fails with
   `DID NOT RAISE` was reopened by a rule you copied: drop the rule, or, if the feature really needs it, update that
   test. This is the safety net, as long as such tests assert the refusal through `sandbox_denials()`.

### Other routes
- The samples drive the application through a scenario in a `learn.py` script, run by `make learn`, and their tests
  always run strict.
- During early development, `python-import=*` in `.py-sandboxes` lets every import through, so learning records
  none. Never put it in `tests.py-sandboxes` alone: learning would then miss the feature's imports, and the strict
  run against `.py-sandboxes` would refuse them one by one. The learned imports need no such shortcut: the sandbox's
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
    { include = "my-package/.py-sanboxes" }
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
