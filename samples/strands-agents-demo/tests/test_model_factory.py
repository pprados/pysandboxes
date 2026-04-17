"""CHAT_MODEL normalization."""

from strands_agents_demo.model_factory import normalize_litellm_model_id


def test_normalize_colon_to_slash() -> None:
    assert normalize_litellm_model_id("openai:gpt-4o-mini") == "openai/gpt-4o-mini"


def test_normalize_slash_unchanged() -> None:
    assert normalize_litellm_model_id("anthropic/claude-3-5-sonnet-20241022") == (
        "anthropic/claude-3-5-sonnet-20241022"
    )


def test_normalize_bare_model_defaults_openai() -> None:
    assert normalize_litellm_model_id("gpt-4o-mini") == "openai/gpt-4o-mini"


def test_normalize_empty_defaults() -> None:
    assert normalize_litellm_model_id("") == "openai/gpt-4o-mini"
