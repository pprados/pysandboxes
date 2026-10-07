# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Regression: under ``bwrap`` the child must import what the parent imports, editable installs included."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote.bwrap_sse_daemon import BWrapSSEDaemon


def _setenv(args: list[str], name: str) -> str:
    for i, arg in enumerate(args):
        if arg == "--setenv" and args[i + 1] == name:
            return args[i + 2]
    raise AssertionError(f"{name} is not set")


def test_a_path_added_by_a_pth_file_reaches_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PYTHONHOME hides the venv, and PYTHONPATH entries get no .pth processing: an editable root must be named."""
    editable_root = tmp_path / "project"
    editable_root.mkdir()
    monkeypatch.setattr(sys, "path", [*sys.path, str(editable_root)])
    with patch("pysandboxes.remote.bwrap_sse_daemon.which_command", return_value="/usr/bin/bwrap"):
        args = list(BWrapSSEDaemon("token")._bwrap_args(EmptyRules, {}, tmp_path / "pipe", tmp_path))
    assert str(editable_root) in _setenv(args, "PYTHONPATH").split(":")
