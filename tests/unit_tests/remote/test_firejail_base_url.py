# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The daemon URL must follow the network the jail really has.

With the stock ``restricted-network yes`` in ``/etc/firejail/firejail.config``, the
jail gets no ``--net`` and the daemon listens on the host loopback. The ping found
it there, but ``base_url`` insisted on an ``eth0`` address and raised
``SystemExit``, which ended the whole calling process.
"""

import ipaddress
from types import SimpleNamespace
from unittest.mock import patch

from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote.firejail_sse_daemon import FireJailSSEDaemon


def _daemon() -> FireJailSSEDaemon:
    daemon = FireJailSSEDaemon("token")
    daemon._process = SimpleNamespace(pid=1234)  # type: ignore[assignment]
    return daemon


def test_a_jail_without_its_own_network_is_reached_on_the_loopback() -> None:
    with patch.object(firejail_sse_daemon, "parse_firejail_net_print", return_value=None):
        assert _daemon().base_url == "http://127.0.0.1:{PORT}"


def test_a_jail_with_its_own_network_is_reached_on_its_address() -> None:
    ip = ipaddress.IPv4Address("10.10.20.2")
    with patch.object(firejail_sse_daemon, "parse_firejail_net_print", return_value=ip):
        assert _daemon().base_url == "http://10.10.20.2:{PORT}"
