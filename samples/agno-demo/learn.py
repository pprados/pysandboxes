# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
r"""Relearn the sample's profiles, one per mode.

Each mode has its own profile, and each is learned in its own mode. Sharing a
single file would grant each mode the other's privileges for nothing, which is
the opposite of what the partial mode is for.

    # partial: only the tool bodies enter the sandbox
    .venv/bin/python learn.py

    # complete: the whole agent runs under python-sb
    .venv/bin/python -m pysandboxes.python_sb \
        --pysandboxes-config=.py-sandboxes-complete \
        --learn=.py-sandboxes-complete learn.py

Learning only ever adds, and it only writes when it observed something the
profile did not already allow -- a run that needs nothing new leaves the file
alone and prints nothing. To shrink a profile, trim it by hand down to its
header and its `net=` rules, then relearn.

Two things learning cannot produce, and that the profiles carry by hand:

- the `net=` rules -- which hosts a tool may reach is the author's decision,
  not an observation;
- the `net=...|IN` transport ports, when a port is forced -- that is the sandbox
  talking to its parent, not the application reaching out.

The tools are called through the wrappers Agno is handed, not through the inner
`@sandbox` functions: in the complete mode that dispatch runs inside the sandbox
too, and a profile learned on the direct call is short of exactly those modules.
"""

from pathlib import Path

from pysandboxes import is_in_sandbox, sandboxes

CONFIG = Path(__file__).parent / ".py-sandboxes"


def drive() -> None:
    from agno_demo.tools import evaluate_expression, fetch_webpage

    print(evaluate_expression("2*(3+4)"))
    print(fetch_webpage("https://www.google.com/")[:80])


if is_in_sandbox():  # complete mode: python-sb already armed the profile
    drive()
else:
    with sandboxes(sandboxes_config=CONFIG, learn=str(CONFIG)):
        drive()
