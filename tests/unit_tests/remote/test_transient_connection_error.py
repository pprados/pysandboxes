# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A readiness ping retries a reset connection, not a system fault.

The daemon ping loops must ride out the startup race where the
listening socket is already open while the server finishes
initialising, so the accepted connection is reset (errno 104, surfaced
by aiohttp as ``ClientOSError``). Catching ``ClientOSError`` wholesale
would be too broad: a real fault such as ``EMFILE`` or ``ENOMEM`` would
be swallowed and only reported once the ping budget ran out, under a
message about the sandbox tooling.
"""

import errno

import pytest  # type: ignore[import-untyped]
from aiohttp import ClientConnectorError, ClientOSError

from pysandboxes.remote.tools import is_transient_connection_error


@pytest.mark.parametrize(
    "code",
    [errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE],
)
def test_startup_races_are_retried(code: int) -> None:
    assert is_transient_connection_error(ClientOSError(code, "transient"))


@pytest.mark.parametrize(
    "code",
    [errno.EMFILE, errno.ENOMEM, errno.EACCES, errno.EADDRINUSE],
)
def test_system_faults_are_not_retried(code: int) -> None:
    assert not is_transient_connection_error(ClientOSError(code, "real fault"))


def test_missing_errno_is_not_retried() -> None:
    """An opaque error is surfaced rather than retried blindly."""
    assert not is_transient_connection_error(ClientOSError("opaque"))


def test_connector_errors_keep_their_own_clause() -> None:
    """ClientConnectorError derives from ClientOSError.

    The loops catch it in its own clause, ahead of the ClientOSError
    one, so a plain connection refusal never reaches the errno filter.
    This pins that inheritance, which is what makes the clause order
    matter.
    """
    assert issubclass(ClientConnectorError, ClientOSError)
