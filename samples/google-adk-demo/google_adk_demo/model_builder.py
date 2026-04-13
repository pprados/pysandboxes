"""Map ``CHAT_MODEL`` to an ADK-native Gemini id or a ``LiteLlm`` connector."""

import os
from typing import Any


def normalize_litellm_model_string(spec: str) -> str:
    """Normalize ``provider:model_id`` to ``provider/model_id`` for LiteLLM.

    - ``provider:model_id``: first ``:`` becomes ``/`` (model id may contain ``/``).
    - LangChain-style ``google_genai:...`` maps to ``gemini/...`` for LiteLLM.
    - A value with only ``/`` (no ``:``) is returned unchanged.
    """
    if ":" not in spec or spec.lower().startswith("http"):
        return spec
    left, right = spec.split(":", 1)
    if left == "google_genai":
        return f"gemini/{right}"
    return f"{left}/{right}"


def _should_use_litellm(raw: str) -> bool:
    s = raw.strip()
    if not s:
        return False
    if s.lower().startswith("http"):
        return False
    return "/" in s or ":" in s


def build_model_from_env() -> Any:
    """Return a Gemini model id (``str``) or ``LiteLlm`` for other providers."""
    raw = os.environ.get("CHAT_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    if not _should_use_litellm(raw):
        return raw
    from google.adk.models.lite_llm import LiteLlm

    litellm_id = normalize_litellm_model_string(raw)
    return LiteLlm(model=litellm_id)
