# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for the process and enforcement lifecycle states."""

import pytest  # type: ignore[import-untyped]

from pysandboxes import lifecycle


def test_nested_enter_calls_keep_the_process_in_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_entered", 0)

    lifecycle.enter()
    lifecycle.enter()
    assert lifecycle.is_in_sandbox()

    lifecycle.leave()
    assert lifecycle.is_in_sandbox()

    lifecycle.leave()
    assert not lifecycle.is_in_sandbox()


def test_leaving_without_entering_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_entered", 0)

    with pytest.raises(AssertionError):
        lifecycle.leave()


def test_sandbox_membership_does_not_imply_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_entered", 0)
    monkeypatch.setattr(lifecycle, "_armed", False)

    lifecycle.enter()

    assert lifecycle.is_in_sandbox()
    assert not lifecycle.is_armed()


def test_arming_does_not_imply_sandbox_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_entered", 0)
    monkeypatch.setattr(lifecycle, "_armed", False)

    lifecycle.arm()

    assert lifecycle.is_armed()
    assert not lifecycle.is_in_sandbox()


def test_arming_is_logged_once_however_many_entry_points_call_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(lifecycle, "_armed", False)

    with caplog.at_level("DEBUG", logger="pysandboxes.lifecycle"):
        lifecycle.arm()
        first_call = caplog.text.count("lifecycle: armed")
        lifecycle.arm()

    assert first_call == 1
    assert caplog.text.count("lifecycle: armed") == 1
