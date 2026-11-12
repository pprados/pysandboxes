# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` under ``appcontainer``, which blocks the loopback: the destination is a public name.

The kernel layer only grants the network class, the Python guard judges the host. The test needs the Internet and
skips without it.
"""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ALLOWED, DENIED = "example.com", "example.org"

SCRIPT = """
import json, socket

def connect(host, target):
    try:
        socket.create_connection((host, target), timeout=5).close()
        return "CONNECTED"
    except Exception:
        return "REFUSED"

before = connect("{literal}", 443)
address = socket.getaddrinfo("{allowed}", 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
print(json.dumps({{"before": before, "allowed": connect(address, 443),
                  "other_port": connect(address, 80), "by_name": connect("{allowed}", 443),
                  "denied_name": connect("{denied}", 443)}}))
"""


def test_the_guard_opens_the_addresses_of_a_public_name_only_once_resolved(tmp_path: Path) -> None:
    if reason := provider_skip_reason("appcontainer"):
        pytest.skip(reason)
    try:
        literal = socket.gethostbyname(ALLOWED)
        socket.gethostbyname(DENIED)
    except OSError:
        pytest.skip("no Internet access")
    profile = tmp_path / "runtime.profile"
    profile.write_text(
        "os-sandbox=appcontainer\n"
        "net-resolve=runtime\n"
        "python-import=*\n"
        "expose-ro=.\n"
        f"expose-ro={sys.base_prefix}\n"
        f"net=ALLOW|TCP|{ALLOWED}|443|OUT\n"
    )
    script = SCRIPT.format(allowed=ALLOWED, denied=DENIED, literal=literal)
    code = (
        "import sys; from pysandboxes import python_sb; "
        f"sys.argv = ['python-sb', {f'--pysandboxes-config={profile}'!r}, '-c', {script!r}]; "
        "sys.exit(python_sb.main())"
    )

    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT_DIR, capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr[-3000:]
    outcome = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert outcome == {
        "before": "REFUSED",
        "allowed": "CONNECTED",
        "other_port": "REFUSED",
        "by_name": "CONNECTED",
        "denied_name": "REFUSED",
    }
