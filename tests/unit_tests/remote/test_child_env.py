# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The sandbox child gets the environment the rules allow, plus what Windows cannot start without.

Winsock reads SYSTEMROOT to load its providers: a child started without it dies on
``import asyncio`` (``_overlapped``) with WinError 10106, before running anything.
"""

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote.client_subprocess_sse_daemon import _child_env
from pysandboxes.sb_types import Envs


def test_windows_child_keeps_systemroot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")

    assert _child_env(Envs({"TERM": "xterm"})) == {"TERM": "xterm", "SYSTEMROOT": r"C:\Windows"}


def test_posix_child_gets_only_the_allowed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")

    assert _child_env(Envs({"TERM": "xterm"})) == {"TERM": "xterm"}
