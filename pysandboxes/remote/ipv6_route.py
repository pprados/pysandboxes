# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Wait for the IPv6 default route of a sandbox network namespace, which slirp4netns announces by router advertisement.

Without this wait the sandbox code may start before the advertisement is processed, and its first IPv6 connection
fails with ``ENETUNREACH``. No dependency: the sandbox setup process imports it too.
"""

import time

ROUTE_TIMEOUT = 15.0


def has_default_route(route_file: str) -> bool:
    """True when ``route_file`` (``/proc/<pid>/net/ipv6_route``) holds a default route that does not use ``lo``."""
    try:
        with open(route_file) as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[-1] != "lo":
                    return True
    except OSError:
        pass
    return False


def wait_default_route(pid: int | None = None, timeout: float = ROUTE_TIMEOUT) -> bool:
    """Poll until the namespace of ``pid`` has an IPv6 default route; False on timeout.

    ``None`` stands for the calling process, read as ``self``: inside a PID namespace its own pid names another
    process of the host ``/proc``. A timeout is not an error: the sandbox keeps no IPv6 route, so its IPv6 traffic
    fails, which is the safe side.
    """
    route_file = f"/proc/{'self' if pid is None else pid}/net/ipv6_route"
    deadline = time.monotonic() + timeout
    while not has_default_route(route_file):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True
