"""Tool unit tests."""

from unittest.mock import MagicMock, patch

import httpx

from strands_agents_demo.tools import execute_python, fetch_webpage


def test_fetch_webpage_truncates() -> None:
    long_body = "x" * 9000
    with patch("strands_agents_demo.tools.httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.get.return_value.text = long_body
        inst.get.return_value.raise_for_status = MagicMock()
        out = fetch_webpage("https://example.com")
    assert len(out) < len(long_body)
    assert "[truncated]" in out


def test_fetch_webpage_error() -> None:
    with patch("strands_agents_demo.tools.httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.get.side_effect = httpx.RequestError("boom", request=MagicMock())
        out = fetch_webpage("https://example.com")
    assert out.startswith("Error fetching URL:")


def test_execute_python_result() -> None:
    out = execute_python("result = 1 + 1")
    assert "2" in out


def test_execute_python_print() -> None:
    out = execute_python("print('hi')")
    assert "hi" in out


def test_execute_python_syntax_error() -> None:
    out = execute_python("+++")
    assert out.startswith("Error:")
