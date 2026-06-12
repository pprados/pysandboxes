# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Host capability probes, to skip the integration tests the environment cannot run."""

import socket
from functools import cache

from pysandboxes.remote.tools import get_default_interface

# Hostnames from py-sandbox-test.profile that require resolution at config load time
PROFILE_RESOLVE_HOSTS = ("www.google.com",)

NO_DEFAULT_ROUTE_REASON = "The host exposes no default network interface"
NO_PROFILE_DNS_REASON = f"Cannot resolve {', '.join(PROFILE_RESOLVE_HOSTS)} (needed to parse the test profile)"


@cache
def default_route_available() -> bool:
    """Return True when the host exposes a default network interface."""
    return get_default_interface() is not None


@cache
def profile_hosts_resolvable() -> bool:
    """Return True when every hostname used by py-sandbox-test.profile resolves."""
    for hostname in PROFILE_RESOLVE_HOSTS:
        try:
            socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        except OSError:
            return False
    return True
