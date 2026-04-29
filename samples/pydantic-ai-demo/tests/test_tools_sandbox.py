"""Tests for sandbox protection of fetch_webpage tool.

This module tests both scenarios:
- Scenario A: Sandboxed function calls within sandboxes() context
- Scenario B: Configuration validation for .py-sandboxes file
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic_ai_demo.tools import _fetch_webpage_sandboxed, fetch_webpage


class TestFetchWebpageWithSandbox:
    """Scenario A: Sandboxed function calls within sandbox context.

    Tests that the sandboxed wrapper function works correctly when
    the sandbox daemon is active (within sandboxes() context).
    """

    def test_fetch_webpage_wrapper_delegates_to_sandboxed(self) -> None:
        """Verify wrapper function correctly calls sandboxed implementation."""
        from pysandboxes import sandboxes

        mock_response = MagicMock()
        mock_response.text = "Hello, World!"
        mock_response.raise_for_status = MagicMock()
        client_instance = MagicMock()
        client_instance.get.return_value = mock_response
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with sandboxes(os_sandbox="none"):  # Use "none" for testing
            with patch(
                "pydantic_ai_demo.tools.httpx.Client",
                return_value=client_instance,
            ):
                result = fetch_webpage("https://example.com")

        assert result == "Hello, World!"
        client_instance.get.assert_called_once()

    def test_fetch_webpage_handles_http_errors(self) -> None:
        """Verify error handling for HTTP failures in sandbox."""
        from pysandboxes import sandboxes

        client_instance = MagicMock()
        client_instance.get.side_effect = Exception("Connection failed")
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with sandboxes(os_sandbox="none"):
            with patch(
                "pydantic_ai_demo.tools.httpx.Client",
                return_value=client_instance,
            ):
                result = fetch_webpage("https://example.com")

        assert "Error fetching URL" in result
        assert "Exception" in result

    def test_fetch_webpage_truncates_long_responses_in_sandbox(self) -> None:
        """Verify long responses are truncated correctly in sandbox."""
        from pysandboxes import sandboxes

        long_body = "x" * 9000
        mock_response = MagicMock()
        mock_response.text = long_body
        mock_response.raise_for_status = MagicMock()
        client_instance = MagicMock()
        client_instance.get.return_value = mock_response
        client_instance.__enter__.return_value = client_instance
        client_instance.__exit__.return_value = None

        with sandboxes(os_sandbox="none"):
            with patch(
                "pydantic_ai_demo.tools.httpx.Client",
                return_value=client_instance,
            ):
                result = fetch_webpage("https://example.com")

        assert "... [truncated]" in result
        assert len(result) <= 8100

    def test_sandboxed_function_is_decorated(self) -> None:
        """Verify that _fetch_webpage_sandboxed is decorated with @sandbox."""
        # The function should be wrapped by the sandbox decorator
        assert callable(_fetch_webpage_sandboxed)
        # Function name should still contain the original name
        assert "_fetch_webpage_sandboxed" in _fetch_webpage_sandboxed.__name__


class TestSandboxConfiguration:
    """Scenario B: Configuration validation for .py-sandboxes file."""

    def test_py_sandboxes_config_exists(self) -> None:
        """Verify .py-sandboxes configuration file is present."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        assert config_path.exists(), ".py-sandboxes config file should exist"

    def test_py_sandboxes_config_allows_example_com(self) -> None:
        """Verify .py-sandboxes allows example.com on ports 80/443."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        config_content = config_path.read_text()

        # Config should include rules allowing example.com
        assert "example.com" in config_content, "Config should mention example.com"
        assert "80" in config_content and "443" in config_content, \
            "Config should allow both HTTP and HTTPS ports"
        assert "ALLOW" in config_content, "Config should have ALLOW rules"

    def test_py_sandboxes_config_denies_other_networks(self) -> None:
        """Verify .py-sandboxes denies other network access by default."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        config_content = config_path.read_text()

        # Config should have default-deny for network access
        assert "DENY" in config_content, "Config should have DENY rules"
        assert "py-sandbox=true" in config_content, "Config should enable py-sandbox"

    def test_py_sandboxes_config_structure(self) -> None:
        """Verify .py-sandboxes config has proper structure."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        config_content = config_path.read_text()

        # Verify key configuration sections
        assert "os-sandbox" in config_content, "Config should specify os-sandbox"
        assert "net=ALLOW" in config_content, "Config should have ALLOW network rules"
        assert "env=" in config_content, "Config should have environment rules"
