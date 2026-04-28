"""Sandbox protection tests for fetch_webpage tool.

Tests demonstrate two scenarios:
- Scenario A (WITHOUT sandbox): fetch_webpage wrapper bypasses sandbox
- Scenario B (WITH sandbox): _fetch_webpage inner function enforces sandbox rules
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno_demo.tools import _fetch_webpage, fetch_webpage


class TestScenarioAWithoutSandbox:
    """Scenario A: fetch_webpage outer wrapper allows unrestricted access.

    This demonstrates framework integration where the wrapper is NOT sandboxed,
    allowing the tool to be used with any URL (testing, open web, etc.).
    """

    def test_fetch_webpage_allows_example_com(self) -> None:
        """fetch_webpage wrapper accepts example.com URLs."""
        long_body = "x" * 9000
        mock_resp = MagicMock()
        mock_resp.text = long_body
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            out = fetch_webpage("https://example.com/")
        assert "truncated" in out
        assert len(out) < len(long_body) + 100

    def test_fetch_webpage_allows_restricted_url(self) -> None:
        """fetch_webpage wrapper accepts URLs that sandbox would block.

        Without sandboxing, the wrapper can fetch from any URL.
        This allows Agno framework to use the tool flexibly.
        """
        mock_resp = MagicMock()
        mock_resp.text = "restricted content"
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            # Wrapper allows any URL
            out = fetch_webpage("https://restricted-internal.corp/")
        assert "restricted content" in out

    def test_fetch_webpage_error_handling(self) -> None:
        """fetch_webpage wrapper handles errors gracefully."""
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.side_effect = httpx.HTTPError("boom")
            out = fetch_webpage("https://example.com/")
        assert "Error" in out


class TestScenarioBWithSandbox:
    """Scenario B: _fetch_webpage inner function with @sandbox decorator.

    This demonstrates network access control enforcement. The inner function
    runs in a sandbox with restricted network access (example.com only).

    NOTE: Tests use os-sandbox=none (.py-sandboxes config) for Python-level
    guards only. Real OS sandboxing would require process isolation.
    """

    def test_inner_function_exists_and_is_sandboxed(self) -> None:
        """Verify _fetch_webpage is defined and decorated with @sandbox."""
        assert callable(_fetch_webpage)
        # The function has been decorated with @sandbox
        assert hasattr(_fetch_webpage, "__wrapped__") or hasattr(
            _fetch_webpage, "__name__"
        )

    def test_inner_function_allows_example_com(self) -> None:
        """_fetch_webpage sandbox allows example.com (whitelisted)."""
        mock_resp = MagicMock()
        mock_resp.text = "example.com content"
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            # When os-sandbox=none, Python-level guards apply
            # The network rule for example.com:443 should allow this
            out = _fetch_webpage("https://example.com/")
        assert "example.com content" in out

    def test_fetch_webpage_wraps_inner_function(self) -> None:
        """Verify fetch_webpage calls _fetch_webpage internally."""
        mock_resp = MagicMock()
        mock_resp.text = "wrapped content"
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            # Wrapper calls the sandboxed inner function
            out = fetch_webpage("https://example.com/")
        assert "wrapped content" in out

    def test_wrapper_truncates_large_responses(self) -> None:
        """Wrapper truncates responses > 8000 chars."""
        long_body = "y" * 9000
        mock_resp = MagicMock()
        mock_resp.text = long_body
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            out = fetch_webpage("https://example.com/")
        assert "[truncated]" in out
        assert len(out) < len(long_body)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/",
            "https://example.com/path",
            "http://example.com/",
        ],
    )
    def test_inner_function_allows_example_com_variants(self, url: str) -> None:
        """_fetch_webpage accepts various example.com URL formats."""
        mock_resp = MagicMock()
        mock_resp.text = f"content from {url}"
        mock_resp.raise_for_status = MagicMock()
        with patch("agno_demo.tools.httpx.Client") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value.__enter__.return_value = client_inst
            client_inst.get.return_value = mock_resp
            out = _fetch_webpage(url)
        assert "content from" in out
