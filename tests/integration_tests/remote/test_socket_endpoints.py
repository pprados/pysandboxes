# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A real sandboxed child answering RPC over a Unix socket the host bound, py-sandbox armed.

Left out of the Windows collection by ``tests/conftest.py``: its Python has no ``AF_UNIX``, which
``test_socket_endpoints_fallback.py`` covers.
"""

import os
import stat
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandboxes
from pysandboxes._os_sandbox import unsupported_platform_reason
from pysandboxes.remote import client_subprocess_sse_daemon as csd
from tests.integration_tests._env import provider_skip_reason
from tests.unit_tests._unix_sockets import requires_unix_sockets

from .test_rpc import sync_function

config_path = Path(__file__).parent / "py-sandbox-unix.profile"
plain_profile = Path(__file__).parent / "py-sandbox-test.profile"
nonet_profile = Path(__file__).parent / "py-sandbox-nonet.profile"

# A provider the platform does not have gets no row rather than a skip: PYSANDBOXES_FAIL_ON_SKIP fails a skipped run.
UNIX_PROVIDERS = [
    row
    for row in ("subprocess", "landlock", "bwrap", "firejail", "unshare", "qemu", "sandbox-exec")
    if not unsupported_platform_reason(row)
]
NO_NETWORK_PROVIDERS = [row for row in UNIX_PROVIDERS if row != "qemu"]


@pytest.fixture
def bound_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the path of every socket the host binds for the sandbox."""
    paths: list[str] = []
    original = csd.listen_socket

    def recording(endpoint: Any) -> Any:
        paths.append(endpoint.path)
        return original(endpoint)

    monkeypatch.setattr(csd, "listen_socket", recording)
    return paths


@requires_unix_sockets
@pytest.mark.parametrize("os_sandbox", UNIX_PROVIDERS)
def test_rpc_crosses_a_unix_socket(os_sandbox: str, bound_paths: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    if reason := provider_skip_reason(os_sandbox):
        pytest.skip(reason)
    monkeypatch.setenv("OS_SANDBOX", os_sandbox)

    with sandboxes(sandboxes_config=config_path):
        assert sync_function("a", b="1") == "a 1"
        assert len(set(bound_paths)) == 1
        assert stat.S_ISSOCK(os.stat(bound_paths[0]).st_mode)
        # QEMU creates its own socket file with its own mode: the private directory is what keeps others out.
        assert stat.S_IMODE(os.stat(os.path.dirname(bound_paths[0])).st_mode) == 0o700
        if os_sandbox != "qemu":
            assert stat.S_IMODE(os.stat(bound_paths[0]).st_mode) == 0o600

    assert not os.path.exists(os.path.dirname(bound_paths[0]))


@requires_unix_sockets
@pytest.mark.parametrize("os_sandbox", UNIX_PROVIDERS)
def test_a_profile_without_the_key_uses_a_unix_socket(
    os_sandbox: str, bound_paths: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if reason := provider_skip_reason(os_sandbox):
        pytest.skip(reason)
    monkeypatch.setenv("OS_SANDBOX", os_sandbox)

    with sandboxes(sandboxes_config=plain_profile):
        assert sync_function("a", b="2") == "a 2"

    assert len(set(bound_paths)) == 1


@requires_unix_sockets
@pytest.mark.parametrize("os_sandbox", NO_NETWORK_PROVIDERS)
def test_the_channel_needs_no_network_rule(
    os_sandbox: str, bound_paths: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if reason := provider_skip_reason(os_sandbox):
        pytest.skip(reason)
    monkeypatch.setenv("OS_SANDBOX", os_sandbox)

    with sandboxes(sandboxes_config=nonet_profile):
        assert sync_function("a", b="4") == "a 4"

    assert len(set(bound_paths)) == 1
