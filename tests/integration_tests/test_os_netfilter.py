# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Each kernel-backed provider that filters the network holds on its own, with the Python socket guard disarmed.

The OS filter of bwrap could never load, and the one of qemu was never applied by python-sb nor found by the guest
once ``/etc`` was exposed: the Python guard refused in their place, so every suite stayed green. ``py-sandbox=false``
takes that guard out, so only the kernel can refuse here.

The target is a host listener. slirp4netns and QEMU user networking expose loopback as their gateway; Landlock
connects to loopback directly. Firejail connects through a test bridge and targets its gateway address. Each case
runs in its own process, under python-sb and daemon mode (``@sandbox`` within ``sandboxes()``), with a negative
control the same filter lets through.
"""

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from pysandboxes.remote.landlock_daemon import _get_landlock_abi_version

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_GATEWAY = "10.0.2.2"
_PROVIDERS = ("bwrap", "unshare", "qemu", "landlock")
_FIREJAIL_BRIDGE = os.environ.get("PYSANDBOXES_FIREJAIL_TEST_BRIDGE", "docker0")
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
        for reason in (
            provider_skip_reason(provider)
            or (
                "Landlock network rules require ABI v4 (Linux 6.7+)"
                if provider == "landlock" and _get_landlock_abi_version() < 4
                else None
            ),
        )
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


def _target(provider: str) -> str:
    return "127.0.0.1" if provider == "landlock" else _GATEWAY


def _firejail_bridge_ip() -> str | None:
    result = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", _FIREJAIL_BRIDGE], capture_output=True, text=True)
    if result.returncode:
        return None
    for field in result.stdout.split():
        if "/" in field:
            return field.split("/", 1)[0]
    return None


@pytest.fixture
def firejail_bridge_listener() -> Iterator[tuple[str, str, int, int]]:
    reason = provider_skip_reason("firejail")
    if reason:
        pytest.skip(reason)
    bridge_ip = _firejail_bridge_ip()
    if bridge_ip is None:
        pytest.skip(f"Firejail test bridge {_FIREJAIL_BRIDGE!r} has no IPv4 address")

    config = Path("/etc/firejail/firejail.config")
    network_enabled = config.exists() and any(
        line.strip() == "restricted-network no" for line in config.read_text().splitlines()
    )
    if not network_enabled:
        pytest.skip("Firejail OS-network test requires 'restricted-network no'")

    servers: list[socket.socket] = []
    ports: list[int] = []
    threads: list[threading.Thread] = []
    stop = threading.Event()

    def serve(server: socket.socket) -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                server.accept()[0].close()
            except OSError:
                continue

    try:
        for _ in range(2):
            server = socket.socket()
            server.bind((bridge_ip, 0))
            server.listen()
            servers.append(server)
            ports.append(server.getsockname()[1])

        threads = [threading.Thread(target=serve, args=(server,), daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        yield _FIREJAIL_BRIDGE, bridge_ip, ports[0], ports[1]
    finally:
        stop.set()
        for server in servers:
            server.close()
        for thread in threads:
            thread.join()


def _run(
    tmp_path: Path,
    provider: str,
    mode: str,
    port: int,
    allow: str,
    *,
    target_host: str | None = None,
    firejail_bridge: str | None = None,
) -> str:
    # /etc is exposed on purpose: mounted over the qemu guest's own, it once hid iptables-restore from the guest.
    profile = tmp_path / "netfilter.profile"
    firejail_net = f"firejail.net={firejail_bridge}\n" if firejail_bridge else ""
    profile.write_text(
        "".join(
            [
                "py-sandbox=false\n",
                f"os-sandbox={provider}\n",
                firejail_net,
                "python-import=*\n",
                "expose-ro=.\n",
                "expose-ro=/etc\n",
                f"expose-ro={sys.base_prefix}/lib\n",
                f"net=ALLOW|TCP|{allow}|OUT\n",
            ]
        )
    )
    if mode == "python-sb":
        cmd = [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            "-c",
            _PAYLOAD.format(host=target_host or _target(provider), port=port),
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "tests.integration_tests.tst_netfilter_probe",
            str(profile),
            target_host or _target(provider),
            str(port),
        ]
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
    allow_host = "*" if provider == "landlock" else _GATEWAY
    assert "CONNECTED" in _run(tmp_path, provider, mode, host_listener, f"{allow_host}|{host_listener}")


@pytest.mark.parametrize("mode", ("python-sb", "daemon"))
def test_firejail_blocks_a_port_outside_the_allow_rule(
    tmp_path: Path, firejail_bridge_listener: tuple[str, str, int, int], mode: str
) -> None:
    bridge, host, allowed_port, denied_port = firejail_bridge_listener
    result = _run(
        tmp_path,
        "firejail",
        mode,
        denied_port,
        f"{host}|{allowed_port}",
        target_host=host,
        firejail_bridge=bridge,
    )
    assert "REFUSED" in result


@pytest.mark.parametrize("mode", ("python-sb", "daemon"))
def test_firejail_connects_to_a_port_allowed_by_the_os_filter(
    tmp_path: Path, firejail_bridge_listener: tuple[str, str, int, int], mode: str
) -> None:
    bridge, host, allowed_port, _ = firejail_bridge_listener
    result = _run(
        tmp_path,
        "firejail",
        mode,
        allowed_port,
        f"{host}|{allowed_port}",
        target_host=host,
        firejail_bridge=bridge,
    )
    assert "CONNECTED" in result
