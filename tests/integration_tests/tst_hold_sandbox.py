# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Hold a sandbox open, so a test can kill this process and inspect what survives.

Prints ``SANDBOX UP`` once the sandbox answers, then waits. Run as a module:
``python -m tests.integration_tests.tst_hold_sandbox``.
"""

import time

from pysandboxes import sandbox, sandboxes

HOLD_SECONDS = 90


@sandbox
def _ping() -> int:
    return 1


def main() -> None:
    with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
        _ping()
        print("SANDBOX UP", flush=True)
        time.sleep(HOLD_SECONDS)


if __name__ == "__main__":
    main()
