# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Print the environment a sandbox actually sees, by name.

A diagnostic, not a test: it is how the `_EXPECTED_ENVS` allowance in `tst_usage`
was measured, and how to re-measure it for a provider or container image that was
not covered -- qemu and the container harnesses among them. Run as:

    OS_SANDBOX=<provider> TERM=dumb My_ENV=1 python -m pysandboxes.python_sb \
        --pysandboxes-config=tests/integration_tests/py-sandbox-test.profile \
        -m tests.integration_tests.tst_env_dump
"""

import os

from pysandboxes import sandbox, sandboxes


@sandbox
def _seen() -> list[str]:
    return sorted(os.environ)


def main() -> None:
    with sandboxes():
        print("INSIDE=" + ",".join(_seen()), flush=True)


if __name__ == "__main__":
    main()
