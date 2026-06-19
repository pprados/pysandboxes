# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Partial mode must not hand the parent's environment to the sandbox.

In partial mode (a.k.a. split mode) the application keeps all its privileges -- API
tokens included -- and only the ``@sandbox`` functions run isolated. The sandbox must
therefore see the variables whitelisted by the profile, and nothing else.

Run as ``python -m tests.integration_tests.tst_env_leak``: a plain interpreter, so the
parent keeps its real environment. ``python-sb`` strips ``os.environ`` before spawning
anything, which hides a leak in the spawn path itself.
"""

import os
import sys

from pysandboxes import sandbox, sandboxes

SECRET_NAME = "SECRET_TOKEN"

# Whitelisted by py-sandbox-test.profile (env=TERM=..., env=My_ENV=...).
_EXPECTED = ("TERM", "My_ENV")
# Set by the parent process, whitelisted by no rule.
_FORBIDDEN = (SECRET_NAME, "USER")


@sandbox
def _envs_seen_by_the_sandbox() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in _FORBIDDEN + _EXPECTED}


def main() -> int:
    with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
        seen = _envs_seen_by_the_sandbox()

    rc = 0
    for name in _FORBIDDEN:
        if seen[name] is not None:
            # Never echo the value: a leak report must not copy the secret into the logs.
            print(f"KO {name} leaked into the sandbox", file=sys.stderr)
            rc = 1
    for name in _EXPECTED:
        if seen[name] is None:
            print(f"KO {name} is whitelisted by the profile but not visible", file=sys.stderr)
            rc = 1
    if not rc:
        print("OK sandbox sees only the whitelisted environment")
    return rc


if __name__ == "__main__":
    sys.exit(main())
