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
from pysandboxes.e import SandBoxError
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


# QEMU 8.2 refuses a hostfwd=unix: rule: that binary gets the TCP fallback test below instead of a Unix socket row.
def _qemu_refuses_unix_forwarding() -> bool:
    if "qemu" not in UNIX_PROVIDERS or provider_skip_reason("qemu") is not None:
        return False
    from pysandboxes.remote.qemu_sse_daemon import _qemu_accepts_unix_hostfwd, _qemu_binary

    return not _qemu_accepts_unix_hostfwd(_qemu_binary())


QEMU_TCP_ONLY = _qemu_refuses_unix_forwarding()
if QEMU_TCP_ONLY:
    UNIX_PROVIDERS.remove("qemu")
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


if QEMU_TCP_ONLY:

    @requires_unix_sockets
    def test_auto_falls_back_to_tcp_on_a_qemu_without_unix_forwarding(
        bound_paths: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OS_SANDBOX", "qemu")

        with sandboxes(sandboxes_config=plain_profile):
            assert sync_function("a", b="3") == "a 3"

        assert bound_paths == []

    @requires_unix_sockets
    def test_a_forced_unix_socket_is_refused_on_a_qemu_without_unix_forwarding(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OS_SANDBOX", "qemu")

        with pytest.raises(SandBoxError, match="remote-endpoint=unix is impossible"):
            with sandboxes(sandboxes_config=config_path):
                pass


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
