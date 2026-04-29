"""Tests for sandbox integration in smolagents fetch_webpage tool.

Scenario A: Baseline without sandbox (fetch_webpage should work normally).
Scenario B: With sandbox (blocked URLs error, allowed URLs work).
"""

from pathlib import Path

import pytest

from smolagents_demo.tools import fetch_webpage
from samples.conftest import pysandbox_enabled, ALLOWED_URL, BLOCKED_URL


class TestFetchWithoutSandbox:
    """Scenario A: Baseline, no sandbox active."""

    def test_fetch_allowed_url_no_sandbox(self) -> None:
        """Fetch example.com without sandbox (should work)."""
        result = fetch_webpage(ALLOWED_URL)
        assert len(result) > 0
        assert "Error" not in result[:50]


class TestFetchWithSandbox:
    """Scenario B: Sandbox active, enforce network rules."""

    def test_fetch_blocked_url_with_sandbox(self, sandbox_config_deny_all: Path) -> None:
        """Fetch blocked URL with sandbox (should error)."""
        with pysandbox_enabled():
            result = fetch_webpage(BLOCKED_URL)
            assert "Error" in result

    def test_fetch_allowed_url_with_sandbox(self, sandbox_config_allow_example: Path) -> None:
        """Fetch allowed URL with sandbox (should work)."""
        with pysandbox_enabled():
            result = fetch_webpage(ALLOWED_URL)
            assert len(result) > 0
            assert "Error" not in result[:50]
