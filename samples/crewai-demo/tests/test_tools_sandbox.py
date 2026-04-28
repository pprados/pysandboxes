"""Tests for sandboxed HTTP fetch tool: Scenario A (without) and B (with) sandbox."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from crewai_demo.tools import fetch_webpage

# Path to the sandbox config file
CONFIG_PATH = Path(__file__).parent.parent / ".py-sandboxes"


class TestFetchWebpageWithoutSandbox:
    """Scenario A: fetch_webpage without sandbox protection (baseline)."""

    def test_fetch_success_mocked(self) -> None:
        """Test successful HTTP fetch with mocked client (no sandbox)."""
        long_body = "x" * 9000
        mock_response = MagicMock()
        mock_response.text = long_body
        mock_response.raise_for_status = MagicMock()
        client_instance = MagicMock()
        client_instance.get.return_value = mock_response
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with patch("crewai_demo.tools.httpx.Client", return_value=client_instance):
            text = fetch_webpage.run(url="https://example.com")

        assert "... [truncated]" in text
        assert len(text) <= 8100

    def test_fetch_error_mocked(self) -> None:
        """Test HTTP error handling without sandbox."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=Exception("404 Not Found"))
        client_instance = MagicMock()
        client_instance.get.return_value = mock_response
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with patch("crewai_demo.tools.httpx.Client", return_value=client_instance):
            text = fetch_webpage.run(url="https://example.com/missing")

        assert "Error fetching URL:" in text
        assert "404 Not Found" in text

    def test_fetch_forbidden_domain_mocked(self) -> None:
        """Test that fetch without sandbox can reach any domain (no restrictions)."""
        mock_response = MagicMock()
        mock_response.text = "Success: reached restricted.com"
        mock_response.raise_for_status = MagicMock()
        client_instance = MagicMock()
        client_instance.get.return_value = mock_response
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with patch("crewai_demo.tools.httpx.Client", return_value=client_instance):
            text = fetch_webpage.run(url="https://restricted.com")

        assert "Success: reached restricted.com" in text


class TestFetchWebpageWithSandbox:
    """Scenario B: fetch_webpage with sandbox protection."""

    def test_config_exists(self) -> None:
        """Test that sandbox config file exists."""
        assert CONFIG_PATH.exists(), f"Config file not found at {CONFIG_PATH}"

    def test_config_contains_network_rules(self) -> None:
        """Test that config contains expected network rules."""
        config_content = CONFIG_PATH.read_text()
        assert "net=" in config_content, "Config should contain network rules"
        assert "example.com" in config_content, "Config should allow example.com"

    def test_config_denies_other_domains(self) -> None:
        """Test that config denies connections to non-whitelisted domains."""
        config_content = CONFIG_PATH.read_text()
        assert "net=DENY" in config_content, "Config should deny non-whitelisted connections"

    def test_sandboxed_fetch_signature(self) -> None:
        """Test that sandboxed _fetch_webpage function is available."""
        from crewai_demo.tools import _fetch_webpage

        # Verify the function exists and is decorated
        assert callable(_fetch_webpage), "_fetch_webpage should be callable"
        assert hasattr(_fetch_webpage, "__wrapped__"), "_fetch_webpage should be decorated"

    def test_config_allows_https_to_example_com(self) -> None:
        """Test that config allows HTTPS (443) to example.com."""
        config_content = CONFIG_PATH.read_text()
        # Check for explicit allow rule for example.com on port 443
        assert "net=ALLOW" in config_content
        assert "example.com" in config_content
        assert "443" in config_content
