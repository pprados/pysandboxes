# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Probe of test_unshare_runtime_ipv6: ``net-resolve=runtime`` opens the IPv6 address of an allowed name.

Run as ``python -m tests.integration_tests.tst_unshare_runtime_ipv6_probe <workdir> <kernel|guard> [provider]``;
it prints one JSON object. The daemon runs in this process, so the probe points its filtering resolver at a fake
authoritative server of its own. That server answers ``AAAA`` only, with ``fd00::2``: slirp4netns maps that
address of the sandbox to the host loopback ``::1``, where the probe listens, so a connection to it proves the
address was opened and a refusal proves it was not.
"""

import json
import socket
import struct
import sys
import threading
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from unittest.mock import patch

from pysandboxes import egress_filter, sandbox, sandboxes
from pysandboxes.remote import runtime_dns

from .tst_unshare_runtime_probe import ALLOWED_NAME, DENIED_NAME, TTL, _resolver_state

GATEWAY6 = "fd00::2"
AAAA = 28


class FakeAuthority6:
    """A DNS server over TCP on host loopback: ``AAAA`` resolves to the IPv6 gateway of the sandbox, ``A`` to none."""

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
                    qtype = struct.unpack(">H", packet[-4:-2])[0]
                    if qtype == AAAA:
                        answer = b"\xc0\x0c" + struct.pack(">HHIH", AAAA, 1, TTL, 16) + IPv6Address(GATEWAY6).packed
                        reply = packet[:2] + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0) + packet[12:] + answer
                    else:
                        reply = packet[:2] + struct.pack(">HHHHH", 0x8180, 1, 0, 0, 0) + packet[12:]
                    conn.sendall(struct.pack(">H", len(reply)) + reply)
                except OSError:
                    continue

    def close(self) -> None:
        self._stop.set()
        self._server.close()


class Listener6:
    """A TCP listener on the IPv6 loopback of the host, accepting and closing every connection."""

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET6)
        self._server.bind(("::1", 0))
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
        infos = socket.getaddrinfo(name, port, socket.AF_INET6, socket.SOCK_STREAM)
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

    query = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x1c\x00\x01"
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as udp:
        udp.settimeout(3)
        try:
            udp.sendto(query, ("2001:4860:4860::8888", 53))
            udp.recv(512)
            out["hard_coded_resolver"] = "ANSWERED"
        except Exception:
            out["hard_coded_resolver"] = "REFUSED"

    time.sleep(ttl + 4)
    out["after_expiry"] = connect(addresses[0], port)
    out["relearned"] = connect(resolve(allowed_name)[0], port)
    return out


def main() -> int:
    work, layers = Path(sys.argv[1]), sys.argv[2]
    provider = sys.argv[3] if len(sys.argv) > 3 else "unshare"
    authority, allowed, other = FakeAuthority6(), Listener6(), Listener6()
    egress_filter.MIN_LEARNED_TTL = egress_filter.MAX_LEARNED_TTL = TTL
    runtime_dns.get_upstream_dns = lambda: [IPv4Address("127.0.0.1")]
    real = runtime_dns.RuntimeDns
    started: list[runtime_dns.RuntimeDns] = []

    def start_resolver(rules: tuple, servers: list, **kwargs: str) -> runtime_dns.RuntimeDns:
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
        "expose-ro=/etc\n"
        f"expose-ro={sys.base_prefix}/lib\n"
        f"net=ALLOW|TCP|{ALLOWED_NAME}|{allowed.port}|OUT\n"
    )
    try:
        with sandboxes(sandboxes_config=str(profile)):
            result = _probe(ALLOWED_NAME, DENIED_NAME, GATEWAY6, allowed.port, other.port, TTL)
    finally:
        authority.close()
        allowed.close()
        other.close()
    print(json.dumps({"result": result, "questions": len(authority.questions), **_resolver_state(started)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
