# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Open a sandbox, resolve one hostname through it, close it and exit.

Prints ``RESOLVED <address>``. The resolution matters as much as the exit: under
``unshare`` it reads the ``resolv.conf`` the setup stage bind-mounts into the
chroot, so a test can tell "nothing was left behind" from "the DNS files were
moved somewhere the sandbox cannot see". Run as a module:
``python -m tests.integration_tests.tst_resolve_once``.
"""

import socket

from pysandboxes import sandbox, sandboxes


@sandbox
def _resolve() -> str:
    return socket.gethostbyname("www.google.com")


def main() -> None:
    with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
        print("RESOLVED", _resolve(), flush=True)


if __name__ == "__main__":
    main()
