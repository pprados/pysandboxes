# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Provider capability probes used by integration tests."""

import subprocess

import pytest

from tests.integration_tests import _env


def test_provider_skip_reason_detects_nested_firejail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_env, "provider_unavailable_reason", lambda _provider: None)
    monkeypatch.setattr(_env.Path, "exists", lambda _path: False)
    monkeypatch.setattr(
        _env.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "", "Warning: an existing sandbox was detected."
        ),
    )

    assert _env.provider_skip_reason("firejail") == "firejail cannot add a nested sandbox here"
