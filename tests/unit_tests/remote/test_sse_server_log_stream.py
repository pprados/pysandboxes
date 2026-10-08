# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Regression: the sandbox daemon's uvicorn logs go to stderr, never to the stdout the child inherits."""

import logging
import sys

import pytest

from pysandboxes.remote.sse_server_daemon import create_uvicorn_daemon


def test_uvicorn_logs_to_stderr_when_nothing_configured_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """An MCP server on a stdio transport reads JSON-RPC on that stdout: "ERROR:uvicorn.error:..." broke it."""
    uvicorn_logger = logging.getLogger("uvicorn")
    monkeypatch.setattr(uvicorn_logger, "handlers", [])
    monkeypatch.setattr(uvicorn_logger, "propagate", uvicorn_logger.propagate)
    monkeypatch.setattr(sys, "stdout", sys.__stdout__)
    monkeypatch.setattr(sys, "stderr", sys.__stderr__)
    server = create_uvicorn_daemon("token", "127.0.0.1", 0)
    log_config = server.config.log_config
    assert isinstance(log_config, dict)
    assert {handler["stream"] for handler in log_config["handlers"].values()} == {"ext://sys.stderr"}
