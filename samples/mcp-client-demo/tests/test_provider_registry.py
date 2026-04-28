"""Tests for the SQLite provider URL registry."""

from pathlib import Path

import pytest

from mcp_simple_chatbot.provider_registry import (
    ensure_registry,
    get_chat_completions_url,
    parse_chat_model,
    resolve_chat_model,
)


def test_parse_chat_model_ok() -> None:
    assert parse_chat_model("openai/gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert parse_chat_model("xai/grok-4-fast-non-reasoning") == (
        "xai",
        "grok-4-fast-non-reasoning",
    )


def test_parse_chat_model_rejects_bad() -> None:
    with pytest.raises(ValueError, match="CHAT_MODEL"):
        parse_chat_model("gpt-4o-mini")
    with pytest.raises(ValueError, match="Invalid"):
        parse_chat_model("openai/")


def test_registry_seeded_and_lookup(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    ensure_registry(db)
    assert get_chat_completions_url("openai", db_path=db).startswith(
        "https://api.openai"
    )
    assert get_chat_completions_url("groq", db_path=db).startswith("https://api.groq")
    assert get_chat_completions_url("mistral", db_path=db).startswith(
        "https://api.mistral"
    )
    assert get_chat_completions_url("ollama", db_path=db).startswith("http://127.0.0.1")
    with pytest.raises(KeyError, match="Unknown"):
        get_chat_completions_url("unknown", db_path=db)


def test_resolve_chat_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    ensure_registry(db)
    monkeypatch.setenv("CHAT_MODEL", "openai/gpt-4o-mini")
    r = resolve_chat_model(db_path=db)
    assert r.provider == "openai"
    assert r.model == "gpt-4o-mini"
    assert "openai.com" in r.chat_completions_url
