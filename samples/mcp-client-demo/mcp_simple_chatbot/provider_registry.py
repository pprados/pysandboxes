# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""SQLite registry mapping provider ids to OpenAI-compatible chat completions URLs."""

import logging
import os
import sqlite3
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

# OpenAI-compatible /chat/completions bases (provider id → URL).
_DEFAULT_SEED: tuple[tuple[str, str], ...] = (
    ("cerebras", "https://api.cerebras.ai/v1/chat/completions"),
    ("deepseek", "https://api.deepseek.com/v1/chat/completions"),
    ("fireworks", "https://api.fireworks.ai/inference/v1/chat/completions"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions"),
    ("mistral", "https://api.mistral.ai/v1/chat/completions"),
    ("ollama", "http://127.0.0.1:11434/v1/chat/completions"),
    ("openai", "https://api.openai.com/v1/chat/completions"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
    ("together", "https://api.together.xyz/v1/chat/completions"),
    ("xai", "https://api.x.ai/v1/chat/completions"),
)


class ResolvedChatModel(NamedTuple):
    """Provider id, remote model name, and chat completions endpoint."""

    provider: str
    model: str
    chat_completions_url: str


def default_registry_path() -> Path:
    """Default path for the provider URL registry (next to this package)."""
    override = os.getenv("CHAT_PROVIDER_URLS_DB")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "provider_urls.sqlite"


def ensure_registry(db_path: Path | None = None) -> Path:
    """Create the SQLite file and seed known providers if missing."""
    path = db_path if db_path is not None else default_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY NOT NULL,
                chat_completions_url TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO providers (id, chat_completions_url) VALUES (?, ?)",
            _DEFAULT_SEED,
        )
        conn.commit()
    logger.debug("Provider registry ready at %s", path)
    return path


def list_provider_ids(db_path: Path | None = None) -> list[str]:
    """Return known provider ids (sorted)."""
    path = ensure_registry(db_path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT id FROM providers ORDER BY id").fetchall()
    return [r[0] for r in rows]


def get_chat_completions_url(provider: str, db_path: Path | None = None) -> str:
    """Resolve the chat completions URL for a provider id."""
    path = ensure_registry(db_path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT chat_completions_url FROM providers WHERE id = ?",
            (provider,),
        ).fetchone()
    if row is None:
        known = ", ".join(list_provider_ids(db_path))
        raise KeyError(
            f"Unknown LLM provider {provider!r}. "
            f"Add a row to the registry (see CHAT_PROVIDER_URLS_DB) or use one of: {known}"
        )
    return row[0]


def parse_chat_model(chat_model: str) -> tuple[str, str]:
    """
    Parse ``CHAT_MODEL`` as ``provider/model`` (e.g. ``openai/gpt-4o-mini``).

    Only the first slash separates provider from model id; the rest is the model name.
    """
    chat_model = chat_model.strip()
    if "/" not in chat_model:
        raise ValueError(
            "CHAT_MODEL must look like 'provider/model', e.g. 'openai/gpt-4o-mini'"
        )
    provider, model = chat_model.split("/", 1)
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        raise ValueError(f"Invalid CHAT_MODEL: {chat_model!r}")
    return provider, model


def resolve_chat_model(
    chat_model: str | None = None, db_path: Path | None = None
) -> ResolvedChatModel:
    """Resolve ``CHAT_MODEL`` env (or argument) to provider, model name, and URL."""
    raw = chat_model if chat_model is not None else os.getenv("CHAT_MODEL")
    if not raw:
        raise ValueError(
            "CHAT_MODEL is not set (e.g. export CHAT_MODEL=openai/gpt-4o-mini)"
        )
    provider, model = parse_chat_model(raw)
    url = get_chat_completions_url(provider, db_path=db_path)
    return ResolvedChatModel(provider, model, url)
