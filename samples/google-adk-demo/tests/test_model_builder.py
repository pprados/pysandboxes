"""CHAT_MODEL normalization (no live LLM)."""

import pytest

from google_adk_demo.model_builder import build_model_from_env, normalize_litellm_model_string


def test_normalize_litellm_colon_to_slash() -> None:
    assert normalize_litellm_model_string("openai/gpt-4o-mini") == "openai/gpt-4o-mini"
    assert normalize_litellm_model_string("openai:gpt-4o-mini") == "openai/gpt-4o-mini"
    assert normalize_litellm_model_string("google_genai:gemini-2.0-flash") == "gemini/gemini-2.0-flash"


def test_normalize_preserves_slash_in_model_id() -> None:
    assert normalize_litellm_model_string("foo:bar/baz") == "foo/bar/baz"


def test_build_model_native_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    m = build_model_from_env()
    assert m == "gemini-2.0-flash"


def test_build_model_litellm_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "openai:gpt-4o-mini")
    m = build_model_from_env()
    assert type(m).__name__ == "LiteLlm"
    assert getattr(m, "model", None) == "openai/gpt-4o-mini"


def test_build_model_native_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "gemini-2.5-flash")
    assert build_model_from_env() == "gemini-2.5-flash"
