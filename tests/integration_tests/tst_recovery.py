# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Kill the sandbox with SIGKILL, and report whether it comes back.

Run as a module with ``OS_SANDBOX`` naming the backend: ``python -m tests.integration_tests.tst_recovery``.
One process per backend: a backend that does not recover leaves its daemon half dead, which would fail the next
backend started in the same process. Prints one ``RESULT <json>`` line, whatever happens afterwards.
"""

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from pysandboxes import _os_sandbox, sandbox, sandboxes

ANSWER_WITHIN_SECONDS = 30


@sandbox()
def _echo(value: str) -> str:
    return value


def _sandbox_pids() -> list[int]:
    """The interpreters running the sandbox side: the launcher the daemon holds may be a wrapper around one."""
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if b"main_sandbox" in (entry / "cmdline").read_bytes():
                    found.append(int(entry.name))
            except OSError:
                continue
    return found


def main() -> None:
    result: dict[str, object] = {"answered": False, "restarted": False, "left": []}
    try:
        with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
            assert _echo("before") == "before"
            daemon: Any = _os_sandbox._current_daemon
            assert daemon is not None and daemon._process is not None
            first_pid = daemon._process.pid
            killed = _sandbox_pids()
            for pid in killed:
                os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + ANSWER_WITHIN_SECONDS
            while time.monotonic() < deadline and not result["answered"]:
                try:
                    result["answered"] = _echo("after") == "after"
                except Exception:  # noqa: BLE001 - calls fail while the watchdog starts the sandbox again
                    time.sleep(1)
            result["restarted"] = daemon._process is not None and daemon._process.pid != first_pid
            result["left"] = [pid for pid in killed if Path(f"/proc/{pid}").exists()]
            result["killed"] = len(killed)
    except BaseException as error:  # noqa: BLE001 - the verdict is reported even when the shutdown fails
        result["error"] = f"{type(error).__name__}: {error}"[:300]
    print("RESULT " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
