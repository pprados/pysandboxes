# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a gVisor guest can do with a host Unix socket, which is why gVisor refuses ``remote-endpoint=unix``.

``--host-uds=none`` (what the provider passes) must keep host sockets out of reach, and a listening socket handed
down with ``-pass-fd`` is not usable by the guest. If either changes, the provider can be revisited.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote.gvisor_bundle import build_oci_spec, exposures
from pysandboxes.remote.gvisor_sse_daemon import GVisorSSEDaemon
from tests.integration_tests._env import provider_skip_reason
from tests.unit_tests._unix_sockets import requires_unix_sockets

GUEST = """
import socket, sys
out = []
try:
    c = socket.socket(socket.AF_UNIX); c.settimeout(5); c.connect(sys.argv[1] + "/s"); c.sendall(b"hi")
    out.append("path:" + c.recv(10).decode())
except OSError as e:
    out.append("path:" + str(e.errno))
try:
    listener = socket.socket(fileno=7); listener.settimeout(8); conn, _ = listener.accept()
    out.append("fd:" + conn.recv(10).decode())
except OSError as e:
    out.append("fd:" + str(e.errno))
print("RESULT " + " ".join(out))
"""

pytestmark = [requires_unix_sockets]


def _serve(path: str) -> socket.socket:
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(8)

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            conn.recv(10)
            conn.sendall(b"pong")
            conn.close()

    threading.Thread(target=loop, daemon=True).start()
    return server


@pytest.fixture
def base() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="gvx"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _guest_result(base: Path, host_uds: str) -> str:
    """Run the probe in a gVisor guest that sees the directory of a host socket and of a handed-down listener."""
    shared = base / "d"
    shared.mkdir()
    work = base / "w"
    for sub in ("rootfs", "guest", "state"):
        (work / sub).mkdir(parents=True)
    (work / "empty").touch()
    server = _serve(str(shared / "s"))
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(shared / "p"))
    listener.listen(8)
    host_fd = os.dup(listener.fileno())
    os.set_inheritable(host_fd, True)
    runtime = GVisorSSEDaemon._runtime_paths()
    read_only, read_write = exposures(EmptyRules, runtime_paths=runtime, guest_dir=str(work / "guest"))
    spec = build_oci_spec(
        rootfs=str(work / "rootfs"),
        args=[sys.executable, "-c", GUEST, str(shared)],
        env={"PYTHONHOME": sys.base_prefix, "PYTHONPATH": os.pathsep.join(p for p in runtime if os.path.isdir(p))},
        mounts_ro=read_only,
        mounts_rw=[*read_write, str(shared)],
        masks=[],
        empty_file=str(work / "empty"),
        cwd="/",
    )
    (work / "config.json").write_text(json.dumps(spec))

    def knock() -> None:
        time.sleep(3)
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(5)
                client.connect(str(shared / "p"))
                client.sendall(b"hello")
        except OSError:
            pass

    threading.Thread(target=knock, daemon=True).start()
    command = [
        "unshare", "--user", "--map-root-user", "--net", "--",
        str(shutil.which("runsc")), "--ignore-cgroups", "--network=host", f"--host-uds={host_uds}",
        "--platform=systrap", f"--root={work / 'state'}", "run", "-pass-fd", f"{host_fd}:7",
        f"--bundle={work}", f"pysb-uds-{os.getpid()}",
    ]  # fmt: skip
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=90, pass_fds=(host_fd,), check=False)
    finally:
        server.close()
        listener.close()
        os.close(host_fd)
    result = [line for line in run.stdout.splitlines() if line.startswith("RESULT")]
    assert result, run.stderr[-400:]
    return result[0]


@pytest.fixture(autouse=True)
def _gvisor_available() -> None:
    if reason := provider_skip_reason("gvisor"):
        pytest.skip(reason)


def test_the_provider_setting_keeps_host_sockets_out_of_reach(base: Path) -> None:
    assert "path:111" in _guest_result(base, "none")  # ECONNREFUSED


def test_a_listening_socket_handed_down_cannot_accept(base: Path) -> None:
    assert "fd:22" in _guest_result(base, "none")  # EINVAL: imported, but not a socket the guest can accept on
