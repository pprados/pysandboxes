"""Tests for tools (HTTP mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autogen_demo.tools import execute_python, fetch_webpage


@pytest.mark.asyncio
async def test_execute_python_result_variable() -> None:
    out = await execute_python("result = 2 + 3")
    assert "5" in out


@pytest.mark.asyncio
async def test_execute_python_import_re_allowed() -> None:
    code = r"""import re
m = re.search(r'(\d+)', 'a42b')
result = int(m.group(1))
"""
    out = await execute_python(code)
    assert "42" in out


@pytest.mark.asyncio
async def test_execute_python_import_os_blocked() -> None:
    out = await execute_python("import os")
    assert "Error:" in out
    assert "not allowed" in out


@pytest.mark.asyncio
async def test_execute_python_unterminated_string_includes_hint() -> None:
    out = await execute_python('html = "<x')  # unterminated string literal
    assert "unterminated" in out.lower() or "SyntaxError" in out
    assert "Hint:" in out


@pytest.mark.asyncio
async def test_fetch_webpage_truncates() -> None:
    long_body = "x" * 9000
    mock_response = MagicMock()
    mock_response.text = long_body
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("autogen_demo.tools.httpx.AsyncClient", return_value=mock_client):
        text = await fetch_webpage("https://example.com")

    assert "... [truncated]" in text
    assert len(text) <= 8100
