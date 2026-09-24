# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A missing binary must be named for what it is.

``_prepare_unshare_config`` checks for ``unshare`` then for ``iptables``, and used to
log "unshare not found." for both: a host with unshare installed but no iptables was
told to install what it already had.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pysandboxes.remote import unshare_sse_daemon
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon


def _prepare_with(monkeypatch: pytest.MonkeyPatch, installed: set[str]) -> None:
    monkeypatch.setattr(
        unshare_sse_daemon,
        "which_command",
        lambda command: Path("/usr/bin") / command if command in installed else None,
    )
    # Both checks exit before touching self or the rules, so stand-ins are enough.
    UnshareSSEDaemon._prepare_unshare_config(MagicMock(), MagicMock(), Path("pipe"), "chroot")


def test_missing_iptables_is_reported_as_iptables(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
        _prepare_with(monkeypatch, installed={"unshare"})

    assert "iptables not found." in caplog.text
    assert "unshare not found." not in caplog.text


def test_missing_unshare_is_reported_first(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
        _prepare_with(monkeypatch, installed=set())

    assert "unshare not found." in caplog.text
