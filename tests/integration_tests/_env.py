# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Host capability probes, to skip the integration tests the environment cannot run."""

import platform
import socket
from functools import cache

from pysandboxes.remote.landlock_daemon import landlock_user_available
from pysandboxes.remote.tools import (
    get_default_interface,
    unshare_user_namespace_available,
    which_command,
)

# Hostnames from py-sandbox-test.profile that require resolution at config load time
PROFILE_RESOLVE_HOSTS = ("www.google.com",)

# Every OS sandbox backend a test can be parametrized over. `none` is excluded: it is the
# no-op provider, so a guard test would assert nothing there.
ALL_OS_SANDBOX: tuple[str, ...] = (
    "subprocess",
    "qemu",
    "unshare",
    "firejail",
    "landlock",
    "bwrap",
)

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


def provider_skip_reason(os_sandbox: str) -> str | None:
    """Return why ``os_sandbox`` cannot run here, or None when it can.

    Covers only what the backend itself needs -- its binary, its kernel feature. A
    test whose *profile* needs something more (a resolvable hostname, a default
    route) adds that check on top; those belong to the scenario, not to the backend.

    Args:
        os_sandbox: Backend name, as accepted by ``os-sandbox=``.

    Returns:
        A human-readable reason to pass to ``pytest.skip``, or None.
    """
    if os_sandbox == "firejail" and not which_command("firejail"):
        return "firejail not installed"
    if os_sandbox == "unshare" and not unshare_user_namespace_available():
        return "unshare/slirp4netns missing or user namespaces not permitted"
    if os_sandbox == "landlock" and not landlock_user_available():
        return "Landlock not available (kernel < 5.13 or not Linux)"
    if os_sandbox == "bwrap" and not which_command("bwrap"):
        return "bwrap not installed"
    if os_sandbox == "qemu":
        arch = platform.machine()
        if not which_command(f"qemu-system-{arch}") and not which_command("qemu-system-x86_64"):
            return "QEMU not installed"
    return None
