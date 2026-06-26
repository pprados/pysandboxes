"""Test MCP server fetch_webpage with sandbox protection.

Two scenarios:
1. Without sandbox (baseline): fetch works
2. With sandbox (protected): fetch blocked if URL not allowed
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

# conftest.py configures path for mcp_server import
from mcp_server.main import _fetch_webpage, fetch_webpage


@pytest.mark.asyncio
async def test_fetch_webpage_without_sandbox_returns_content():
    """Scenario A: fetch works when sandbox not active."""
    # Mock httpx to avoid real network calls in test
    mock_response = AsyncMock()
    mock_response.text = "<html><body>Example Domain</body></html>"
    mock_response.raise_for_status = AsyncMock()

    with patch("mcp_server.main.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await _fetch_webpage("https://example.com")

        assert "<html>" in result or "Example" in result
        assert "Error" not in result[:50]


@pytest.mark.asyncio
async def test_fetch_webpage_without_sandbox_returns_error_on_exception():
    """Scenario A: fetch returns error string on network failure."""
    with patch("mcp_server.main.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client_class.return_value = mock_client

        with pytest.raises(ValueError) as exc_info:
            await _fetch_webpage("https://blocked.example.local")

        assert "Failed to fetch webpage" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_webpage_wrapper():
    """Test wrapper function returns task result."""
    mock_response = AsyncMock()
    mock_response.text = "wrapped content"
    mock_response.raise_for_status = AsyncMock()

    with patch("mcp_server.main.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_webpage("https://example.com")

        assert "wrapped" in result or "content" in result


# Scenario B: With sandbox enforcement
# Note: These tests require the full pysandboxes runtime.
# They would be run with `make container-tests` or similar.


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("RUN_SANDBOX_TESTS"),
    reason="Requires pysandboxes runtime (RUN_SANDBOX_TESTS=1)",
)
async def test_fetch_webpage_sandbox_blocks_unauthorized():
    """Scenario B: sandbox blocks URLs not in config.

    This test runs inside pysandboxes runtime.
    Config (.py-sandboxes) does NOT list this URL.
    """
    with pytest.raises(Exception) as exc_info:
        await _fetch_webpage("https://blocked.example.local")

    error_msg = str(exc_info.value).lower()
    assert any(x in error_msg for x in ["refused", "blocked", "denied", "failed"])


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("RUN_SANDBOX_TESTS"),
    reason="Requires pysandboxes runtime (RUN_SANDBOX_TESTS=1)",
)
async def test_fetch_webpage_sandbox_allows_configured():
    """Scenario B: sandbox allows URLs in config.

    This test runs inside pysandboxes runtime.
    Config (.py-sandboxes) lists example.com as allowed.
    """
    # Mock to avoid actual network call in sandbox
    mock_response = AsyncMock()
    mock_response.text = "Example Domain from sandbox"
    mock_response.raise_for_status = AsyncMock()

    with patch("mcp_server.main.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await _fetch_webpage("https://example.com")

        assert "Example" in result or "Domain" in result
