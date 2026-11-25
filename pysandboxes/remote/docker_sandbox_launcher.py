# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Host side of the docker-sandbox provider: creates the sandbox, runs the payload in it, removes it.

Run as a script by ``python -I docker_sandbox_launcher.py <plan.json> <args...>``, never imported: it stays standard
library only. The plan names the ``sbx`` commands to run. The config of the sandboxed program comes from the FIFO named
by ``--_named-pipe`` and heads the standard input of the payload; with ``--_python-sb`` the standard input of the caller
follows. A second ``sbx exec``, whose standard input this process holds, kills the payload when this process dies.
"""

import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from typing import Any

_PAYLOAD_UID = 2000
_SETUP_FAILED = 70
_CHUNK = 65536


def _die_with_parent(parent: int) -> None:
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)
    if os.getppid() != parent:
        sys.exit(0)


def _run(command: list[str], *, quiet: bool = False) -> int:
    """Run an ``sbx`` command without noise; its error output is shown only when it fails."""
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    if done.returncode != 0 and done.stderr and not quiet:
        print(done.stderr, end="", file=sys.stderr)
    return done.returncode


def _split_args(args: list[str]) -> tuple[str, bool, list[str]]:
    """Return the FIFO of the config, whether the caller's standard input follows it, and the payload arguments."""
    fifo = ""
    relay = False
    rest: list[str] = []
    index = 0
    while index < len(args):
        if args[index] == "--_named-pipe":
            fifo = args[index + 1]
            index += 2
            continue
        relay = relay or args[index] == "--_python-sb"
        rest.append(args[index])
        index += 1
    return fifo, relay, rest


def _copy(source: int, target: int) -> None:
    while chunk := os.read(source, _CHUNK):
        view = memoryview(chunk)
        while view:
            view = view[os.write(target, view) :]


def _feed(process: subprocess.Popen[bytes], fifo: str, relay: bool) -> None:
    assert process.stdin is not None
    target = process.stdin.fileno()
    try:
        config = os.open(fifo, os.O_RDONLY)
        try:
            _copy(config, target)
        finally:
            os.close(config)
        if relay:
            _copy(0, target)
    except BrokenPipeError:
        pass
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass


def _owner_is_dead(name: str) -> bool:
    """Tell whether a ``pysb-<pid>-<id>`` sandbox belongs to a process that no longer exists."""
    parts = name.split("-")
    if len(parts) != 3 or parts[0] != "pysb" or not parts[1].isdigit():
        return False
    try:
        os.kill(int(parts[1]), 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _remove_stale(sbx: str, plan: dict[str, Any]) -> None:
    """Remove the sandbox a killed launcher left (its published port would block this one) and the dead owners'."""
    listing = subprocess.run(
        [sbx, "ls", "--quiet"], capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False
    )
    orphans = [name for name in listing.stdout.split() if _owner_is_dead(name)]
    for name in [*plan.get("stale", []), *orphans]:
        _run([sbx, "rm", "--force", name], quiet=True)


def _setup(sbx: str, plan: dict[str, Any]) -> bool:
    """Create the sandbox, give it its rules and verify them; report the failure on the standard error."""
    name = str(plan["name"])
    _remove_stale(sbx, plan)
    if _run([sbx, "create", *plan["create"]]) != 0:
        print(f"docker-sandbox: sbx could not create {name}", file=sys.stderr)
        return False
    for verb, resources in (("allow", plan["allow"]), ("deny", plan["deny"])):
        if resources and _run([sbx, "policy", verb, "network", "--sandbox", name, ",".join(resources)]) != 0:
            print(f"docker-sandbox: sbx refused the {verb} rules {resources}", file=sys.stderr)
            return False
    checks = [(target, True) for target in plan["allow_checks"]] + [(plan["canary"], False)]
    for target, allowed in checks:
        status = _run([sbx, "policy", "check", "network", "--sandbox", name, str(target)], quiet=True)
        if (status == 0) != allowed:
            print(
                f"docker-sandbox: the policy of {name} does not {'allow' if allowed else 'deny'} {target}",
                file=sys.stderr,
            )
            return False
    return True


def main(argv: list[str]) -> int:
    """Run the plan: returns the exit status of the payload, or ``_SETUP_FAILED``."""
    plan = json.loads(argv[1])
    _die_with_parent(int(plan["parent"]))
    sbx = shutil.which("sbx", path=plan["path"]) or "sbx"
    name = str(plan["name"])
    fifo, relay, payload_args = _split_args(argv[2:])
    reaper: subprocess.Popen[bytes] | None = None
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    try:
        if not _setup(sbx, plan):
            return _SETUP_FAILED
        reaper = subprocess.Popen(
            [sbx, "exec", "-i", "-u", "root", name, "sh", "-c", f"read _; pkill -9 -u {_PAYLOAD_UID}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        main_process = subprocess.Popen(
            [
                sbx,
                "exec",
                "-i",
                "-u",
                "root",
                name,
                "sh",
                "-c",
                str(plan["script"]),
                "docker-sandbox-guest",
                *payload_args,
            ],
            stdin=subprocess.PIPE,
        )
        threading.Thread(target=_feed, args=(main_process, fifo, relay), daemon=True).start()
        return main_process.wait()
    finally:
        if reaper is not None and reaper.stdin is not None:
            try:
                reaper.stdin.write(b"\n")
                reaper.stdin.close()
                reaper.wait(timeout=10)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                reaper.kill()
        subprocess.run([sbx, "rm", "--force", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
