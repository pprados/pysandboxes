# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Skip marker for the tests that need a real ``AF_UNIX`` socket, which a restricted environment may refuse."""

import socket

import pytest  # type: ignore[import-untyped]


def _unix_sockets_available() -> bool:
    try:
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
    except (AttributeError, OSError):
        return False
    return True


requires_unix_sockets = pytest.mark.skipif(
    not _unix_sockets_available(), reason="this environment does not allow AF_UNIX sockets"
)
