"""Build a ChatCompletionClient from ``CHAT_MODEL`` (provider + model id)."""

import os

from autogen_core.models import ChatCompletionClient, ModelInfo
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_ext.models.ollama import OllamaChatCompletionClient
from autogen_ext.models.openai import OpenAIChatCompletionClient

# Gemini OpenAI-compatible endpoint (see https://ai.google.dev/gemini-api/docs/openai )
_GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def normalize_chat_model_spec(spec: str) -> str:
    """Normalize ``provider/model`` to ``provider:model`` for parsing.

    - If ``:`` already present (and not a URL scheme), return unchanged.
    - If ``provider/model`` with a single slash, convert to ``:``.
    """
    if ":" in spec:
        return spec
    if "/" not in spec:
        return spec
    left, right = spec.split("/", 1)
    if left and right and not left.lower().startswith("http"):
        return f"{left}:{right}"
    return spec


def parse_provider_and_model(spec: str) -> tuple[str, str]:
    """Return (provider_key, model_id). Bare ``model_id`` defaults to provider ``openai``."""
    normalized = normalize_chat_model_spec(spec.strip())
    if ":" not in normalized:
        return "openai", normalized
    provider, model_id = normalized.split(":", 1)
    if not provider or not model_id:
        raise ValueError(f"Invalid CHAT_MODEL={spec!r}; expected provider:model_id or provider/model_id")
    return provider.strip().lower().replace("-", "_"), model_id.strip()


def build_chat_completion_client() -> ChatCompletionClient:
    """Instantiate a client from ``CHAT_MODEL`` (``provider:model`` or ``provider/model``).

    Supported providers:

    - ``openai`` — OpenAI API (``OPENAI_API_KEY``, optional ``OPENAI_BASE_URL``).
    - ``anthropic`` — Anthropic (``ANTHROPIC_API_KEY``, optional ``ANTHROPIC_BASE_URL``).
    - ``ollama`` — local Ollama (default base URL ``http://127.0.0.1:11434``, override with ``OLLAMA_BASE_URL``).
    - ``google_genai`` / ``gemini`` — Gemini via OpenAI-compatible API (``GOOGLE_API_KEY``, optional ``GEMINI_BASE_URL``).
    """
    raw = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")
    provider, model_id = parse_provider_and_model(raw)

    if provider == "openai":
        kwargs = {"model": model_id}
        if base_url := os.environ.get("OPENAI_BASE_URL"):
            kwargs["base_url"] = base_url
        return OpenAIChatCompletionClient(**kwargs)

    if provider == "anthropic":
        kwargs = {"model": model_id}
        if base_url := os.environ.get("ANTHROPIC_BASE_URL"):
            kwargs["base_url"] = base_url
        return AnthropicChatCompletionClient(**kwargs)

    if provider == "ollama":
        kwargs = {"model": model_id}
        if base_url := os.environ.get("OLLAMA_BASE_URL"):
            kwargs["base_url"] = base_url
        return OllamaChatCompletionClient(**kwargs)

    if provider in ("google_genai", "gemini", "google"):
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        base_url = os.environ.get("GEMINI_BASE_URL", _GEMINI_OPENAI_BASE)
        return OpenAIChatCompletionClient(
            model=model_id,
            api_key=api_key,
            base_url=base_url,
            model_info=ModelInfo(
                vision=True,
                function_calling=True,
                json_output=True,
                family="unknown",
                structured_output=True,
            ),
        )

    raise ValueError(
        f"Unsupported CHAT_MODEL provider {provider!r}. " "Use openai, anthropic, ollama, or google_genai (gemini)."
    )
