"""Tests for CLI model spec normalization (no live LLM)."""

from langchain_demo.main import _normalize_chat_model_spec


def test_normalize_chat_model_slash_to_colon() -> None:
    assert _normalize_chat_model_spec("openai/gpt-4o-mini") == "openai:gpt-4o-mini"
    assert _normalize_chat_model_spec("groq/llama-3.3-70b-versatile") == "groq:llama-3.3-70b-versatile"
    assert _normalize_chat_model_spec("openai:gpt-4o-mini") == "openai:gpt-4o-mini"
    assert _normalize_chat_model_spec("google_genai:gemini-2.0-flash") == "google_genai:gemini-2.0-flash"


def test_normalize_colon_with_slash_in_model_id_unchanged() -> None:
    assert _normalize_chat_model_spec("foo:bar/baz") == "foo:bar/baz"
