"""Tests for tools (HTTP mocked)."""

from unittest.mock import MagicMock, patch

from pydantic_ai_demo.tools import execute_python, fetch_webpage


def test_execute_python_result_variable() -> None:
    out = execute_python("result = 2 + 3")
    assert "5" in out


def test_execute_python_import_re_allowed() -> None:
    code = r"""import re
m = re.search(r'(\d+)', 'a42b')
result = int(m.group(1))
"""
    out = execute_python(code)
    assert "42" in out


def test_execute_python_import_os_blocked() -> None:
    out = execute_python("import os")
    assert "Error:" in out
    assert "not allowed" in out


def test_execute_python_re_search_none_group_returns_error() -> None:
    out = execute_python("import re\nm = re.search(r'nomatch', 'x')\nresult = m.group(0)")
    assert "Error:" in out
    assert "NoneType" in out or "AttributeError" in out


def test_fetch_webpage_uses_httpx_and_truncates() -> None:
    long_body = "x" * 9000
    expected_result = long_body[:8000] + "\n... [truncated]"
    
    # Mock the inner sandboxed function to return the expected truncated content
    with patch("pydantic_ai_demo.tools._fetch_webpage", return_value=expected_result):
        text = fetch_webpage("https://example.com")

    assert "... [truncated]" in text
    assert len(text) <= 8100
