# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Probe of test_unshare_runtime_dns: ``net-resolve=runtime`` under a provider, with only the kernel to refuse.

Run as ``python -m tests.integration_tests.tst_unshare_runtime_probe <workdir> <kernel|guard|python-sb> [provider]``;
the provider is ``unshare`` by default.
``kernel`` disarms the Python socket guard so only the firewall can refuse; ``guard`` arms it, so both layers judge;
``python-sb`` runs the one-shot ``python-sb -c`` entry point in this process, guard armed. It prints a JSON object per
line: the daemon modes one, ``python-sb`` the sandbox's own line and then ours.

The unshare daemon runs in this process, so the probe points its filtering resolver at a fake authoritative server
of its own (the real one asks port 53 of the host resolvers) and shortens the learned TTL. The name the server answers
resolves to the host loopback gateway of slirp4netns, the only address a sandbox can reach on this machine, so a
connection to it proves the address was opened, and a refusal proves it was not.
"""

import json
import socket
import struct
import sys
import threading
from ipaddress import IPv4Address
from pathlib import Path
from unittest.mock import patch

from pysandboxes import egress_filter, python_sb, sandbox, sandboxes
from pysandboxes.remote import runtime_dns
from pysandboxes.remote.runtime_dns import RuntimeDns

GATEWAY = "10.0.2.2"
ALLOWED_NAME = "app.test.example"
DENIED_NAME = "other.test.example"
TTL = 3
MICROVM_LINES = (
    "qemu.microvm_optional_paths=/etc/ssl,/etc/ca-certificates,/usr/share/ca-certificates\n"
    "qemu.microvm_empty_paths=/etc/pki\n"
)


class FakeAuthority:
    """A DNS server over TCP on host loopback: every name resolves to the gateway of the sandbox."""

    def __init__(self) -> None:
        self.questions: list[bytes] = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self._server.settimeout(0.2)
        self.port: int = self._server.getsockname()[1]
        self._stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                continue
            with conn:
                try:
                    size = struct.unpack(">H", conn.recv(2))[0]
                    packet = conn.recv(size)
                    self.questions.append(packet)
                    answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, TTL, 4) + IPv4Address(GATEWAY).packed
                    reply = packet[:2] + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0) + packet[12:] + answer
                    conn.sendall(struct.pack(">H", len(reply)) + reply)
                except OSError:
                    continue

    def close(self) -> None:
        self._stop.set()
        self._server.close()


class Listener:
    """A TCP listener on the host loopback, accepting and closing every connection."""

    def __init__(self) -> None:
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self._server.settimeout(0.2)
        self.port: int = self._server.getsockname()[1]
        self._stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                self._server.accept()[0].close()
            except OSError:
                continue

    def close(self) -> None:
        self._stop.set()
        self._server.close()


@sandbox
def _probe(allowed_name: str, denied_name: str, gateway: str, port: int, other_port: int, ttl: int) -> dict:
    import socket
    import time

    def connect(host: str, target: int) -> str:
        try:
            socket.create_connection((host, target), timeout=3).close()
            return "CONNECTED"
        except Exception:  # the kernel drops (OSError), the armed Python guard raises its own refusal
            return "REFUSED"

    def resolve(name: str) -> list:
        infos = socket.getaddrinfo(name, port, socket.AF_INET, socket.SOCK_STREAM)
        return sorted({info[4][0] for info in infos})

    out: dict = {"literal_before_resolution": connect(gateway, port)}
    addresses = resolve(allowed_name)
    out["resolved"] = addresses
    out["allowed_port"] = connect(addresses[0], port)
    out["other_port"] = connect(addresses[0], other_port)
    try:
        resolve(denied_name)
        out["denied_name"] = "RESOLVED"
    except socket.gaierror:
        out["denied_name"] = "NXDOMAIN"

    query = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.settimeout(3)
        try:
            udp.sendto(query, ("8.8.8.8", 53))
            udp.recv(512)
            out["hard_coded_resolver"] = "ANSWERED"
        except Exception:
            out["hard_coded_resolver"] = "REFUSED"

    time.sleep(ttl + 4)
    out["after_expiry"] = connect(addresses[0], port)
    out["relearned"] = connect(resolve(allowed_name)[0], port)
    return out


def _script(port: int, other_port: int) -> str:
    """What ``python-sb -c`` runs in the sandbox: one JSON line, like the daemon-mode probe."""
    return f"""
import json, socket

def connect(host, target):
    try:
        socket.create_connection((host, target), timeout=3).close()
        return "CONNECTED"
    except Exception:
        return "REFUSED"

before = connect("{GATEWAY}", {port})
address = socket.getaddrinfo("{ALLOWED_NAME}", {port}, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
print(json.dumps({{"literal_before_resolution": before, "resolved": [address],
                  "allowed_port": connect(address, {port}), "other_port": connect(address, {other_port})}}))
"""


def _resolver_state(started: list[RuntimeDns]) -> dict:
    """Whether the resolver of the sandbox that ran is gone: its loopback port, UDP and TCP, can be bound again."""
    if not started:
        return {"resolver_started": False}
    port = started[-1]._port
    for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
        with socket.socket(socket.AF_INET, kind) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                return {"resolver_started": True, "resolver_port_free": False}
    return {"resolver_started": True, "resolver_port_free": True}


def main() -> int:
    work, layers = Path(sys.argv[1]), sys.argv[2]
    provider = sys.argv[3] if len(sys.argv) > 3 else "unshare"
    authority, allowed, other = FakeAuthority(), Listener(), Listener()
    egress_filter.MIN_LEARNED_TTL = egress_filter.MAX_LEARNED_TTL = TTL
    runtime_dns.get_upstream_dns = lambda: [IPv4Address("127.0.0.1")]
    real = runtime_dns.RuntimeDns
    started: list[RuntimeDns] = []

    def start_resolver(rules: tuple, servers: list, **kwargs: str) -> RuntimeDns:
        started.append(real(rules, servers, upstream_port=authority.port, upstream_timeout=3.0, **kwargs))
        return started[-1]

    patch.object(runtime_dns, "RuntimeDns", start_resolver).start()
    profile = work / "runtime.profile"
    profile.write_text(
        f"py-sandbox={'false' if layers == 'kernel' else 'true'}\n"
        f"os-sandbox={provider}\n"
        "net-resolve=runtime\n"
        "python-import=*\n"
        "expose-ro=.\n"
        f"{'' if provider.startswith('qemu') else 'expose-ro=/etc' + chr(10)}"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{ALLOWED_NAME}|{allowed.port}|OUT\n"
        f"{MICROVM_LINES if provider == 'qemu-microvm' else ''}"
    )
    try:
        if layers == "python-sb":
            sys.argv = ["python-sb", f"--pysandboxes-config={profile}", "-c", _script(allowed.port, other.port)]
            code = python_sb.main()
            print(json.dumps({"exit_code": code, "questions": len(authority.questions), **_resolver_state(started)}))
            return 0
        with sandboxes(sandboxes_config=str(profile)):
            result = _probe(ALLOWED_NAME, DENIED_NAME, GATEWAY, allowed.port, other.port, TTL)
    finally:
        authority.close()
        allowed.close()
        other.close()
    print(json.dumps({"result": result, "questions": len(authority.questions), **_resolver_state(started)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
