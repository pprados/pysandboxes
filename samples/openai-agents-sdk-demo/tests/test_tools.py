"""Tests for fetch_webpage and execute_python."""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from openai_agents_sdk_demo.tools import execute_python_impl, fetch_webpage_impl


def test_fetch_webpage_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html><title>Hi</title></html>"
    mock_resp.raise_for_status = MagicMock()

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        assert "google.com" in url
        return mock_resp

    class FakeClient:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> MagicMock:
            return fake_get(url, **kwargs)

    monkeypatch.setattr(httpx, "Client", lambda **_: FakeClient())
    out = fetch_webpage_impl("https://www.google.com")
    assert "Hi" in out


def test_execute_python_result() -> None:
    out = execute_python_impl("result = 21 * 2")
    assert "42" in out


def test_execute_python_print() -> None:
    out = execute_python_impl('print("hello")')
    assert "hello" in out
