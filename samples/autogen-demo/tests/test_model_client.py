"""Tests for CHAT_MODEL parsing (no live LLM)."""

import pytest

from autogen_demo.model_client import normalize_chat_model_spec, parse_provider_and_model


def test_normalize_slash_to_colon() -> None:
    assert normalize_chat_model_spec("openai/gpt-4o-mini") == "openai:gpt-4o-mini"
    assert normalize_chat_model_spec("openai:gpt-4o-mini") == "openai:gpt-4o-mini"


def test_parse_provider_and_model() -> None:
    assert parse_provider_and_model("openai:gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert parse_provider_and_model("anthropic/claude-3-7-sonnet-20250219") == (
        "anthropic",
        "claude-3-7-sonnet-20250219",
    )


def test_parse_bare_model_defaults_openai() -> None:
    assert parse_provider_and_model("gpt-4o-mini") == ("openai", "gpt-4o-mini")


def test_parse_invalid_empty() -> None:
    with pytest.raises(ValueError):
        parse_provider_and_model("openai:")
