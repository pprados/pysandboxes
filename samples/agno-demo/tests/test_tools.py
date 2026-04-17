"""Tool behavior with mocked HTTP."""

from unittest.mock import MagicMock, patch

import httpx

from agno_demo.tools import execute_python, fetch_webpage


def test_fetch_webpage_truncates() -> None:
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


def test_fetch_webpage_error_string() -> None:
    with patch("agno_demo.tools.httpx.Client") as client_cls:
        client_inst = MagicMock()
        client_cls.return_value.__enter__.return_value = client_inst
        client_inst.get.side_effect = httpx.HTTPError("boom")
        out = fetch_webpage("https://example.com/")
    assert "Error" in out


def test_execute_python_result() -> None:
    out = execute_python("result = 1 + 1")
    assert "2" in out
