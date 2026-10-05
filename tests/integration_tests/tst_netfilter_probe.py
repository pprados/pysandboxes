# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Daemon-mode half of test_os_netfilter: a ``@sandbox`` function connects, the parent prints the outcome.

Run as ``python -m tests.integration_tests.tst_netfilter_probe <profile> <host> <port>``.
"""

import socket
import sys

from pysandboxes import sandbox, sandboxes


@sandbox
def _connect(host: str, port: int) -> str:
    try:
        socket.create_connection((host, port), timeout=5).close()
        return "CONNECTED"
    except OSError as e:
        return f"REFUSED {type(e).__name__}"


def main() -> int:
    profile, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    with sandboxes(sandboxes_config=profile):
        print(_connect(host, port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
