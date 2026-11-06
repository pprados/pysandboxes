# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Open a sandbox, resolve one hostname through it, close it and exit.

Prints ``RESOLVED <address>``. The resolution matters as much as the exit: under
``unshare`` it reads the ``resolv.conf`` the setup stage bind-mounts into the
chroot, so a test can tell "nothing was left behind" from "the DNS files were
moved somewhere the sandbox cannot see". Run as a module:
``python -m tests.integration_tests.tst_resolve_once``.
"""

import os
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pysandboxes import _os_sandbox, sandbox, sandboxes

if TYPE_CHECKING:
    from pysandboxes.remote.client_subprocess_sse_daemon import BaseSubProcessDaemon


@sandbox
def _resolve() -> str:
    return socket.gethostbyname("github.com")


def main() -> None:
    started = time.monotonic()
    with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
        if os.environ.get("OS_SANDBOX") == "qemu-microvm":
            daemon = cast("BaseSubProcessDaemon | None", _os_sandbox._current_daemon)
            assert daemon is not None and daemon._process is not None
            pid = daemon._process.pid
            print(f"FIRST_SSE_SECONDS {time.monotonic() - started:.3f}", flush=True)
            print(
                "QEMU_RSS_KIB",
                Path(f"/proc/{pid}/status").read_text().split("VmRSS:")[1].splitlines()[0].strip(),
                flush=True,
            )
            starttime = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            print(f"OWNED_QEMU {pid} {starttime}", flush=True)
        print("RESOLVED", _resolve(), flush=True)


if __name__ == "__main__":
    main()
