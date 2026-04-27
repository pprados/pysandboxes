"""Tool tests (no network)."""

from unittest.mock import MagicMock

import httpx
import pytest

from google_adk_demo.tools import execute_python, fetch_webpage


def test_execute_python_result() -> None:
    out = execute_python("result = 40 + 2")
    assert "42" in out


def test_execute_python_print() -> None:
    out = execute_python("print('hello')")
    assert "hello" in out


def test_fetch_webpage_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html><title>Hi</title></html>"
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=mock_client))
    text = fetch_webpage("https://example.com/")
    assert "Hi" in text
