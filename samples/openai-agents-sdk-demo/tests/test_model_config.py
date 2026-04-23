"""Tests for CHAT_MODEL normalization."""

from openai_agents_sdk_demo.model_config import normalize_chat_model_spec


def test_default_empty() -> None:
    assert normalize_chat_model_spec("") == "gpt-4o-mini"


def test_bare_openai_id() -> None:
    assert normalize_chat_model_spec("gpt-4o-mini") == "gpt-4o-mini"


def test_openai_prefix_colon() -> None:
    assert normalize_chat_model_spec("openai:gpt-4o-mini") == "gpt-4o-mini"


def test_openai_prefix_slash() -> None:
    assert normalize_chat_model_spec("openai/gpt-4o-mini") == "gpt-4o-mini"


def test_litellm_colon() -> None:
    assert (
        normalize_chat_model_spec("litellm:anthropic/claude-sonnet-4-20250514")
        == "litellm/anthropic/claude-sonnet-4-20250514"
    )


def test_litellm_slash_passthrough() -> None:
    s = "litellm/openrouter/openai/gpt-4o-mini"
    assert normalize_chat_model_spec(s) == s


def test_provider_slash_to_litellm() -> None:
    assert (
        normalize_chat_model_spec("anthropic/claude-sonnet-4-20250514") == "litellm/anthropic/claude-sonnet-4-20250514"
    )
