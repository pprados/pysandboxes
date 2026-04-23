"""Tests for CHAT_MODEL normalization."""

from smolagents_demo.model_builder import normalize_lite_llm_model_id


def test_normalize_colon_to_slash() -> None:
    assert normalize_lite_llm_model_id("openai:gpt-4o-mini") == "openai/gpt-4o-mini"


def test_normalize_slash_unchanged() -> None:
    assert normalize_lite_llm_model_id("anthropic/claude-3-5-sonnet-latest") == "anthropic/claude-3-5-sonnet-latest"


def test_normalize_default_empty() -> None:
    assert normalize_lite_llm_model_id("") == "openai/gpt-4o-mini"


def test_normalize_bare_model() -> None:
    assert normalize_lite_llm_model_id("gpt-4o-mini") == "gpt-4o-mini"
