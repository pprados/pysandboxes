# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The channel that lets the host open and close learned addresses in the firewall of a VM guest.

``net-resolve=runtime`` adds rules to the ``LEARNED`` chain while the sandboxed program waits for a name to resolve.
The guest daemon serves its requests on one event loop, so a blocking function would also block a request sent
through it: the guest runs this tiny server in a process of its own, behind a second forwarded port. That process
starts before the Python guards are armed, which would refuse it ``iptables`` like any program of the sandbox,
and ends when the daemon that started it does. A request is one JSON line carrying the token and the ``iptables``
arguments, answered by the return code of ``iptables``.
"""

import hmac
import json
import os
import select
import socket
import subprocess
import sys
import threading
from typing import Callable

TIMEOUT = 10.0
READY_TIMEOUT = 30.0
_VERBS = ("-A", "-D")
_CHAIN = "LEARNED"


def _run_iptables(argv: list[str]) -> int:
    return subprocess.run(argv, check=False, capture_output=True, timeout=TIMEOUT).returncode


def handle(line: bytes, token: str, iptables: str, run: Callable[[list[str]], int] = _run_iptables) -> int:
    """The return code for one request; 1 for a refused one. Only an add or a delete in ``LEARNED`` is run.

    pre: len(iptables) > 0
    post: __return__ >= 0
    """
    try:
        request = json.loads(line)
        argv = request["argv"]
        sent = str(request["token"]).encode()
    except (ValueError, KeyError, TypeError):
        return 1
    if not hmac.compare_digest(sent, token.encode()):
        return 1
    if not (isinstance(argv, list) and len(argv) >= 3 and all(isinstance(a, str) for a in argv)):
        return 1
    if argv[0] not in _VERBS or argv[1] != _CHAIN:
        return 1
    return run([iptables, *argv])


def _serve_one(conn: socket.socket, token: str, iptables: str, run: Callable[[list[str]], int]) -> None:
    with conn:
        conn.settimeout(TIMEOUT)
        try:
            line = conn.makefile("rb").readline(65536)
            conn.sendall(f"{handle(line, token, iptables, run)}\n".encode())
        except OSError:
            return


def serve(
    port: int, token: str, iptables: str, run: Callable[[list[str]], int] = _run_iptables, host: str = "0.0.0.0"
) -> socket.socket:
    """Listen on ``port`` in a daemon thread and return the listening socket (closing it ends the server)."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(8)

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=_serve_one, args=(conn, token, iptables, run), daemon=True).start()

    threading.Thread(target=loop, name="guest-learned", daemon=True).start()
    return server


def send(port: int, token: str, argv: list[str], host: str = "127.0.0.1") -> int:
    """Ask the guest at ``host:port`` to run ``iptables`` with ``argv``; its return code, 1 when unreachable."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as conn:
            conn.sendall(json.dumps({"token": token, "argv": argv}).encode() + b"\n")
            return int(conn.makefile("rb").readline().strip() or 1)
    except (OSError, ValueError):
        return 1


def start_helper(port: int, token: str, iptables: str) -> "subprocess.Popen[bytes]":
    """Start the process that serves ``port``, and return once it listens.

    The token goes through its stdin, and closing the pipe ends it. The helper imports this package before it
    listens, which takes seconds on a guest: a program that resolved a name sooner would have its address refused.
    """
    helper = subprocess.Popen(
        [sys.executable, "-c", "from pysandboxes.remote.guest_learned import main; main()", str(port), iptables],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)},
    )
    assert helper.stdin is not None and helper.stdout is not None
    helper.stdin.write(token.encode() + b"\n")
    helper.stdin.flush()
    if select.select([helper.stdout], [], [], READY_TIMEOUT)[0]:
        helper.stdout.readline()
    return helper


def main() -> None:
    """Entry of the helper: ``port iptables`` as arguments, the token as the first line of stdin."""
    port, iptables = int(sys.argv[1]), sys.argv[2]
    token = sys.stdin.readline().rstrip("\n")
    serve(port, token, iptables)
    print("ready", flush=True)
    sys.stdin.read()
