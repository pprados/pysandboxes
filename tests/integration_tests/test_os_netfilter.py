# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Each kernel-backed provider that filters the network holds on its own, with the Python socket guard disarmed.

The OS filter of bwrap could never load, and the one of qemu was never applied by python-sb nor found by the guest
once ``/etc`` was exposed: the Python guard refused in their place, so every suite stayed green. ``py-sandbox=false``
takes that guard out, so only the kernel can refuse here.

The target is a listener on the host loopback, which slirp4netns and QEMU user networking both expose to the sandbox
as their gateway: offline and deterministic. Each case runs in its own process, under python-sb and in daemon mode
(``@sandbox`` within ``sandboxes()``), with a negative control the same filter lets through.
"""

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_GATEWAY = "10.0.2.2"
_PROVIDERS = ("bwrap", "unshare", "qemu")
_PAYLOAD = """
import socket
try:
    socket.create_connection(("{host}", {port}), timeout=5).close()
    print("CONNECTED")
except OSError as e:
    print("REFUSED", type(e).__name__)
"""


def _params() -> list:
    return [
        pytest.param(provider, mode, marks=pytest.mark.skipif(bool(reason), reason=reason or ""))
        for provider in _PROVIDERS
        for reason in (provider_skip_reason(provider),)
        for mode in ("python-sb", "daemon")
    ]


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


def _run(tmp_path: Path, provider: str, mode: str, port: int, allow: str) -> str:
    # /etc is exposed on purpose: mounted over the qemu guest's own, it once hid iptables-restore from the guest.
    profile = tmp_path / "netfilter.profile"
    profile.write_text(
        "py-sandbox=false\n"
        f"os-sandbox={provider}\n"
        "python-import=*\n"
        "expose-ro=.\n"
        "expose-ro=/etc\n"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{allow}|OUT\n"
    )
    if mode == "python-sb":
        cmd = [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            "-c",
            _PAYLOAD.format(host=_GATEWAY, port=port),
        ]
    else:
        cmd = [sys.executable, "-m", "tests.integration_tests.tst_netfilter_probe", str(profile), _GATEWAY, str(port)]
    env = {**os.environ, "QEMU_USE_KVM": os.environ.get("QEMU_USE_KVM", "true")}
    result = subprocess.run(cmd, cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


@pytest.mark.parametrize(("provider", "mode"), _params())
def test_a_destination_outside_the_rules_is_dropped_by_the_kernel(
    tmp_path: Path, host_listener: int, provider: str, mode: str
) -> None:
    assert "REFUSED" in _run(tmp_path, provider, mode, host_listener, "192.0.2.1|443")


@pytest.mark.parametrize(("provider", "mode"), _params())
def test_the_same_destination_allowed_by_a_rule_connects(
    tmp_path: Path, host_listener: int, provider: str, mode: str
) -> None:
    """Negative control: the refusal above comes from the filter, not from an unreachable listener."""
    assert "CONNECTED" in _run(tmp_path, provider, mode, host_listener, f"{_GATEWAY}|{host_listener}")
