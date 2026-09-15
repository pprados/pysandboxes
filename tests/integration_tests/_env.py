# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Host capability probes, to skip the integration tests the environment cannot run."""

import platform
import socket
from functools import cache

import pytest  # type: ignore[import-untyped]

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
#
# "qemu-tcg" is not a backend but a second row for the same one, with KVM refused. QEMU
# takes hardware acceleration when /dev/kvm is there and emulates when it is not, and the
# two are different enough -- timings, CPU features -- that a green run under one says
# little about the other. A container is not given /dev/kvm, so emulation is the
# configuration most CI runs land on, and it must be covered on a developer machine that
# does have KVM. On a host without /dev/kvm the two rows are identical and the extra one
# costs a VM boot; that is the price of the row meaning something everywhere else.
ALL_OS_SANDBOX: tuple[str, ...] = (
    "subprocess",
    "qemu",
    "qemu-tcg",
    "unshare",
    "firejail",
    "landlock",
    "bwrap",
)

# Row name -> the value `os-sandbox=` accepts.
_ROW_TO_BACKEND = {"qemu-tcg": "qemu"}


def backend_of(row: str) -> str:
    """Return the ``os-sandbox=`` backend a parametrized row runs on."""
    return _ROW_TO_BACKEND.get(row, row)


def row_profile_lines(row: str) -> str:
    """Return the profile lines that make a row differ from its plain backend."""
    return "qemu.use_kvm=false\n" if row == "qemu-tcg" else ""


def os_sandbox_params() -> list:
    """Return one parametrize row per backend, the emulated one marked ``slow``.

    Emulation is not slightly slower, it is another order of magnitude: the same
    boot measured 12s accelerated and 102s emulated, which turns the whole suite
    from minutes into twenty of them on a host that has KVM. The row still runs by
    default -- it covers what a container does, and a CI run should see it -- but
    ``-m 'not slow'`` buys it back for a quick local loop.
    """
    return [pytest.param(row, marks=[pytest.mark.slow] if row == "qemu-tcg" else []) for row in ALL_OS_SANDBOX]


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
    if backend_of(os_sandbox) == "qemu":
        arch = platform.machine()
        if not which_command(f"qemu-system-{arch}") and not which_command("qemu-system-x86_64"):
            return "QEMU not installed"
    return None
