# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A real sandboxed child answering RPC over a Unix socket instead of a TCP port, py-sandbox armed."""

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandboxes
from pysandboxes.remote.base_sse_daemon import BaseSSESandbox
from pysandboxes.remote.endpoint import UNIX, Endpoint
from tests.unit_tests._unix_sockets import requires_unix_sockets

from .test_rpc import sync_function

config_path = Path(__file__).parent / "py-sandbox-test.profile"


@pytest.fixture
def unix_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[Endpoint]:
    """Make every daemon created during the test talk over a Unix socket in a short private directory."""
    directory = Path(tempfile.mkdtemp(prefix="pysb-"))
    endpoint = Endpoint(UNIX, path=str(directory / "sb.sock"))
    original = BaseSSESandbox.__init__

    def init(self: BaseSSESandbox, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self.endpoint = endpoint

    monkeypatch.setattr(BaseSSESandbox, "__init__", init)
    yield endpoint
    shutil.rmtree(directory, ignore_errors=True)


@requires_unix_sockets
def test_rpc_crosses_a_unix_socket(unix_endpoint: Endpoint) -> None:
    with sandboxes(sandboxes_config=config_path):
        assert sync_function("a", b="1") == "a 1"
        assert stat.S_ISSOCK(os.stat(unix_endpoint.path).st_mode)
        assert stat.S_IMODE(os.stat(unix_endpoint.path).st_mode) == 0o600

    assert not os.path.exists(unix_endpoint.path)
