# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The kernel filter of bwrap holds on its own, with the Python socket guard disarmed.

An unprivileged bwrap could never load its iptables rules from inside the sandbox, and the Python guard masked it:
a profile with socket rules ran with no OS-level filter at all. ``py-sandbox=false`` takes the Python guard out, so
only the kernel can refuse here. The target is a listener on the host loopback, which slirp4netns exposes to the
sandbox as its gateway: offline and deterministic. Each case runs in its own python-sb process.
"""

import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from .._env import provider_skip_reason

_SKIP = provider_skip_reason("bwrap")
_GATEWAY = "10.0.2.2"
_PAYLOAD = """
import socket
try:
    socket.create_connection(("{gateway}", {port}), timeout=5).close()
    print("CONNECTED")
except OSError as e:
    print("REFUSED", type(e).__name__)
"""

pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


@pytest.fixture
def host_listener() -> Iterator[int]:
    """A TCP listener on the host loopback, accepting and closing every connection."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    stop = threading.Event()

    def serve() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                server.accept()[0].close()
            except OSError:
                continue

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    server.close()


def _run(tmp_path: Path, port: int, allow: str) -> str:
    profile = tmp_path / "netfilter.profile"
    profile.write_text(
        "py-sandbox=false\n"
        "os-sandbox=bwrap\n"
        "python-import=*\n"
        "expose-ro=.\n"
        "expose-ro=/etc\n"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{allow}|OUT\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            "-c",
            _PAYLOAD.format(gateway=_GATEWAY, port=port),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_destination_outside_the_rules_is_dropped_by_the_kernel(tmp_path: Path, host_listener: int) -> None:
    assert "REFUSED" in _run(tmp_path, host_listener, "192.0.2.1|443")


def test_the_same_destination_allowed_by_a_rule_connects(tmp_path: Path, host_listener: int) -> None:
    """Negative control: the refusal above comes from the filter, not from an unreachable listener."""
    assert "CONNECTED" in _run(tmp_path, host_listener, f"{_GATEWAY}|{host_listener}")
