---
name: pysandboxes-rules-from-tests
description: Use when a test of a new or changed feature fails because pysandboxes refused an access (RuleModuleNotFoundError, RuleFileNotFoundError, RuleSocketConnectionRefusedError, a python-api or an eval refusal), in a project whose tests run under a .py-sandboxes rule file. Learns the missing rules from the feature's tests, explains each one, and lets the user grant them.
---

# Learn the rules a feature needs from its tests

A new feature often needs a right the rule file does not grant yet: an import, a file, a host. Its tests reveal it,
since they fail on the refusal. This skill turns those refusals into rules the user reviews and grants. The rule
file stays the user's: never widen it without their consent.

## How the tests run

In partial mode, the test does not run in the sandbox. pytest, the test function, its fixtures and its assertions
stay in the pytest process; only the body of each `@sandbox` function runs in a separate process, the sandbox,
started by `with sandboxes()`. Only that body is learned: what pytest imports, reads or writes for itself never
reaches the rules.

## 1. Judge the refusal first

A refusal is the rules working. Check whether the feature needs that access at all: a refusal often reveals a
mistake, a wrong path or a stray network call. Fix the code in that case, and stop here.

## 2. Set up, once per project

Ask the user before adding these two files. `tests.py-sandboxes`, next to `.py-sandboxes`, holds a single line;
learning writes there and only there, below the `include`:

```ini
include ".py-sandboxes"
```

And this `conftest.py`, at the root of the tests. A test marked `sandbox_learn` learns when `SANDBOX_LEARN` is set;
every other test, and every test without the variable, runs strict against `.py-sandboxes`. Each test opens its
own sandbox, and writes its name above the rules it adds:

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

## 3. Mark the tests of the feature

Mark with `@pytest.mark.sandbox_learn` the tests that exercise the feature as it should work. Never mark a test
that checks a refusal: learning never refuses, it records, so that test would add the very rule it was written to
forbid. The marks can stay: without `SANDBOX_LEARN`, they do nothing.

## 4. Learn, with the user's approval each time

Ask the user before every learning run, and say what it means: in learning mode pysandboxes refuses nothing and
runs the code with no OS boundary, so the feature's code runs with no barrier other than the agent's own sandbox,
if it has one, and otherwise with all the rights of the user. Show the command, and run it only once they agree:

```bash
SANDBOX_LEARN=1 pytest -p no:xdist -m sandbox_learn -k "<the tests of the feature>"
```

`-p no:xdist` keeps the run serial: each sandbox rewrites `tests.py-sandboxes` when it closes. Never learn with
`python-sb --learn -m pytest`: it runs pytest itself in the sandbox, and learns pytest. Never put
`python-import=*` in `tests.py-sandboxes`: learning would then miss the feature's imports.

## 5. Explain each learned rule

Below the `include` of `tests.py-sandboxes`, each block sits under the test that asked for it. A rule two tests need
is credited to the first. For each rule, give the test, the line of the feature's code that needs it, and its risk.
The `pysandboxes-review-rules` skill grades them: `git diff -- tests.py-sandboxes` is its input. Propose the rules
to grant, and say why the others should not be.

## 6. Grant the rules

Ask the user for permission to edit `.py-sandboxes`. With it, copy the accepted rules there, each block with its
`# Learned by` line, so that a later review can name the test. Without it, show the exact lines and say where to
paste them, at the end of `.py-sandboxes`. Then put `tests.py-sandboxes` back to its single `include` line, and
delete the `tests.old*` backups learning left beside it.

## 7. Run the whole suite strict

```bash
pytest
```

A test of the feature that still fails is missing a rule that was not granted. A test that checks a refusal and now
fails with `DID NOT RAISE` was reopened by a granted rule: drop the rule, or, if the feature really needs it, ask
the user before changing that test.
