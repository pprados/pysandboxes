"""Tests for tools (HTTP mocked)."""

from unittest.mock import MagicMock, patch

from crewai_demo.tools import execute_python, fetch_webpage


def test_execute_python_result_variable() -> None:
    out = execute_python.run(code="result = 2 + 3")
    assert "5" in out


def test_execute_python_import_re_allowed() -> None:
    code = r"""import re
m = re.search(r'(\d+)', 'a42b')
result = int(m.group(1))
"""
    out = execute_python.run(code=code)
    assert "42" in out


def test_execute_python_import_os_blocked() -> None:
    out = execute_python.run(code="import os")
    assert "Error:" in out
    assert "not allowed" in out


def test_execute_python_re_search_none_group_returns_error() -> None:
    out = execute_python.run(code="import re\nm = re.search(r'nomatch', 'x')\nresult = m.group(0)")
    assert "Error:" in out
    assert "NoneType" in out or "AttributeError" in out


def test_fetch_webpage_uses_httpx_and_truncates() -> None:
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
    client_instance.get.assert_called_once()
