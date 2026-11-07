# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Open and close addresses in the network namespace of a sandbox, from the host, with ``iptables``.

The sandbox holds no capability, so it cannot change its own firewall. The host enters the user namespace the
provider created, where its uid is mapped to root, and the network namespace that user namespace owns, as
``bwrap_sse_daemon._apply_netfilter_from_host`` does. The rules go to the ``LEARNED`` chain, which the ruleset of
``netfilter.runtime_netfilter`` jumps to after the static rules.
"""

import subprocess
from ipaddress import IPv4Address
from typing import Callable

from ..egress_filter import IPAddress, NameRule

NETFILTER_TIMEOUT = 10


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False, capture_output=True, timeout=NETFILTER_TIMEOUT).returncode


class NetnsIptablesEnforcer:
    """``Enforcer`` of a sandbox whose network namespace is held by the process ``pid``.

    A rule is appended once per call and deleted once per call, never deduplicated: two name rules that open the
    same port of the same address each own a copy, so revoking one leaves the other open.
    """

    def __init__(self, pid: int, nsenter: str, iptables: str, run: Callable[[list[str]], int] = _run) -> None:
        self._prefix = [nsenter, "-t", str(pid), "-U", "-n", "--preserve-credentials", iptables]
        self._run = run

    @classmethod
    def via_guest(cls, port: int, token: str) -> "NetnsIptablesEnforcer":
        """Enforcer of a VM guest: the commands go to the thread the guest runs for them, through a forwarded port."""
        from .guest_learned import send

        enforcer = cls(0, "", "", lambda argv: send(port, token, argv))
        enforcer._prefix = []
        return enforcer

    @classmethod
    def via_firejail(
        cls, pid: int, firejail: str, iptables: str, run: Callable[[list[str]], int] = _run
    ) -> "NetnsIptablesEnforcer":
        """Enforcer of a ``firejail`` jail, entered with ``--join-network``, which only root may do."""
        enforcer = cls(pid, "", iptables, run)
        enforcer._prefix = [firejail, f"--join-network={pid}", iptables]
        return enforcer

    def _specs(self, ip: IPAddress, rule: NameRule) -> list[list[str]]:
        ports: list[list[str]] = [
            ["--dport", str(low) if low == high else f"{low}:{high}"] for low, high in rule.ports
        ] or [[]]
        return [["LEARNED", "-d", str(ip), "-p", kind, *port, "-j", "ACCEPT"] for kind in rule.kinds for port in ports]

    def allow(self, ip: IPAddress, rule: NameRule, ttl: int) -> None:
        if not isinstance(ip, IPv4Address):
            return
        done: list[list[str]] = []
        for spec in self._specs(ip, rule):
            if self._run([*self._prefix, "-A", *spec]) != 0:
                for added in done:
                    self._run([*self._prefix, "-D", *added])
                raise OSError(f"iptables -A {' '.join(spec)} failed in the sandbox network namespace")
            done.append(spec)

    def revoke(self, ip: IPAddress, rule: NameRule) -> None:
        if not isinstance(ip, IPv4Address):
            return
        failed = [spec for spec in self._specs(ip, rule) if self._run([*self._prefix, "-D", *spec]) != 0]
        if failed:
            raise OSError(f"iptables -D {' '.join(failed[0])} failed in the sandbox network namespace")
