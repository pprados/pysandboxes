# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The RPC endpoint must not depend on name resolution.

``aiohttp`` resolves with ``AI_ADDRCONFIG``, which fails an IPv4
lookup when no non-loopback interface carries an IPv4 address (a
network namespace holding only ``lo``: ``--network none``, a
restricted CI runner). A hostname would then raise
``ClientConnectorDNSError`` even though the daemon listens on
loopback. An IP literal removes the lookup, and QEMU needs that same
IPv4 literal for ``hostfwd``, which binds TCP on ``0.0.0.0`` only.
"""

import ipaddress
from urllib.parse import urlparse

from pysandboxes.all_rules import AllRules
from pysandboxes.remote.base_sse_daemon import BaseSSESandbox
from pysandboxes.tools import Environ, SyncOrAsyncFunc


class _Sandbox(BaseSSESandbox):
    """Concrete subclass: BaseSSESandbox leaves the lifecycle abstract."""

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Unused: these tests only read the URL the RPC call targets."""

    async def _stop(self, max_pending: int) -> None:
        """Unused: these tests only read the URL the RPC call targets."""

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Unused: these tests only read the URL the RPC call targets."""


def test_base_url_host_is_an_ip_literal() -> None:
    sandbox = _Sandbox(token="a-token", max_connect_retry=1)
    hostname = urlparse(sandbox.base_url.replace("{PORT}", "1")).hostname
    assert hostname is not None
    ipaddress.ip_address(hostname)


def test_base_url_host_is_ipv4_loopback() -> None:
    sandbox = _Sandbox(token="a-token", max_connect_retry=1)
    assert sandbox.host == "127.0.0.1"


def test_the_server_listens_on_the_loopback_by_default() -> None:
    # A provider without a network namespace shares the host network: only the parent must reach the daemon.
    from pysandboxes.remote.daemon_parameters import DaemonParameters
    from pysandboxes.remote.sse_server_daemon import SSEServerDaemon

    assert SSEServerDaemon("token", port=1).bind_host == "127.0.0.1"
    assert DaemonParameters._field_defaults["bind_host"] == "127.0.0.1"
