# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` under ``subprocess``, which has no network namespace: the Python socket guard alone judges.

The sandbox keeps the host network, so there is no firewall to open an address and no resolver to redirect to. The
guard learns the addresses of an allowed name when the program resolves it. The name is ``localhost``, which every
host resolves to its loopback, so no resolver of ours is needed. ``none`` runs plain Python and ``landlock`` closes
the ports of its kernel rules at start, so neither can honour a name that resolves later.
"""

import json
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PROVIDERS = ("subprocess", "landlock", "sandbox-exec")
NAME = "localhost"

SCRIPT = """
import json, socket

def connect(host, target):
    try:
        socket.create_connection((host, target), timeout=3).close()
        return "CONNECTED"
    except Exception:
        return "REFUSED"

before = connect("127.0.0.1", {port})
address = socket.getaddrinfo("{name}", {port}, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
print(json.dumps({{"literal_before_resolution": before, "address": address,
                  "allowed_port": connect(address, {port}), "other_port": connect(address, {other}),
                  "by_name": connect("{name}", {port}), "by_name_other_port": connect("{name}", {other})}}))
"""


@pytest.fixture
def listeners() -> Iterator[tuple[int, int]]:
    with closing(socket.socket()) as allowed, closing(socket.socket()) as other:
        for server in (allowed, other):
            server.bind(("127.0.0.1", 0))
            server.listen(16)
        yield allowed.getsockname()[1], other.getsockname()[1]


@pytest.fixture(params=PROVIDERS)
def provider(request: pytest.FixtureRequest) -> str:
    if reason := provider_skip_reason(str(request.param)):
        pytest.skip(reason)
    return str(request.param)


def test_the_guard_opens_the_addresses_of_an_allowed_name_only_once_resolved(
    tmp_path: Path, provider: str, listeners: tuple[int, int]
) -> None:
    port, other = listeners
    profile = tmp_path / "runtime.profile"
    profile.write_text(
        f"os-sandbox={provider}\n"
        "net-resolve=runtime\n"
        "python-import=*\n"
        "expose-ro=.\n"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{NAME}|{port}|OUT\n"
    )
    script = SCRIPT.format(port=port, other=other, name=NAME)
    code = (
        "import sys; from pysandboxes import python_sb; "
        f"sys.argv = ['python-sb', {f'--pysandboxes-config={profile}'!r}, '-c', {script!r}]; "
        "sys.exit(python_sb.main())"
    )

    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT_DIR, capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr[-3000:]
    outcome = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert outcome == {
        "literal_before_resolution": "REFUSED",
        "address": "127.0.0.1",
        "allowed_port": "CONNECTED",
        "other_port": "REFUSED",
        "by_name": "CONNECTED",
        "by_name_other_port": "REFUSED",
    }
