# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` under ``firejail`` without root is ``pinned``: the firewall of the jail stays exact.

Only root can enter the network namespace of a jail to open an address while the program runs, so the profile keeps
its static firewall. The name is resolved once, at start, and the kernel refuses every other address.
"""

import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from pysandboxes.remote.firejail_sse_daemon import _interface_ipv4
from pysandboxes.remote.tools import get_bridge_interfaces

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

SCRIPT = """
import json, socket

def connect(host, target):
    try:
        socket.create_connection((host, target), timeout=3).close()
        return "CONNECTED"
    except Exception:
        return "REFUSED"

print(json.dumps({{"by_name": connect("{name}", {port}), "other_port": connect("{name}", {other}),
                  "other_host": connect("{other_host}", {port})}}))
"""


@pytest.fixture
def listeners() -> Iterator[tuple[str, int, int]]:
    bridges = get_bridge_interfaces()
    if not bridges:
        pytest.skip("firejail needs a host bridge")
    bridge = next((name for name in bridges if name.startswith("docker")), bridges[0])
    host = str(_interface_ipv4(bridge))
    with closing(socket.socket()) as allowed, closing(socket.socket()) as other:
        for server in (allowed, other):
            server.bind((host, 0))
            server.listen(16)
        yield host, allowed.getsockname()[1], other.getsockname()[1]


@pytest.mark.skipif(os.geteuid() == 0, reason="as root the mode stays runtime")
def test_runtime_without_root_is_pinned_and_the_kernel_stays_exact(
    tmp_path: Path, listeners: tuple[str, int, int]
) -> None:
    if reason := provider_skip_reason("firejail"):
        pytest.skip(reason)
    host, port, other = listeners
    profile = tmp_path / "runtime.profile"
    profile.write_text(
        "os-sandbox=firejail\n"
        "net-resolve=runtime\n"
        "py-sandbox=false\n"
        "python-import=*\n"
        "expose-ro=.\n"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{host}|{port}|OUT\n"
    )
    script = SCRIPT.format(name=host, port=port, other=other, other_host="127.0.0.1")
    code = (
        "import sys; from pysandboxes import python_sb; "
        f"sys.argv = ['python-sb', {f'--pysandboxes-config={profile}'!r}, '-c', {script!r}]; "
        "sys.exit(python_sb.main())"
    )

    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT_DIR, capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr[-3000:]
    assert "falling back to net-resolve=pinned" in result.stderr
    outcome = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert outcome == {"by_name": "CONNECTED", "other_port": "REFUSED", "other_host": "REFUSED"}
