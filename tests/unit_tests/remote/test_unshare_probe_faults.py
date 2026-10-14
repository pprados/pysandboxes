# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The user-namespace probe answers False, never raises, whatever happens to its `unshare` child."""

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from pysandboxes.remote import tools


@pytest.fixture(autouse=True)
def binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "which_command", lambda name: f"/usr/bin/{name}")


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired("unshare", 5), FileNotFoundError("unshare"), PermissionError("denied"), OSError("io")],
    ids=["timeout", "missing", "denied", "os-error"],
)
def test_a_probe_that_cannot_run_is_a_refusal(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    def run(*_: Any, **__: Any) -> Any:
        raise failure

    monkeypatch.setattr(tools.subprocess, "run", run)

    assert tools.unshare_user_namespace_available() is False


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False), (125, False)])
def test_the_exit_status_is_the_answer(monkeypatch: pytest.MonkeyPatch, returncode: int, expected: bool) -> None:
    monkeypatch.setattr(tools.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=returncode))

    assert tools.unshare_user_namespace_available() is expected
