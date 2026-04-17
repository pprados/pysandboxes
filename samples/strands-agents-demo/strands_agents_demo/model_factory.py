"""Build a Strands chat model from ``CHAT_MODEL`` (LiteLLM routing)."""

import os

from strands.models.litellm import LiteLLMModel
from strands.models.model import Model


def normalize_litellm_model_id(spec: str) -> str:
    """Normalize ``CHAT_MODEL`` to LiteLLM ``provider/model`` form.

    - Values that already use ``provider/model`` are returned unchanged.
    - ``provider:model_id`` (single colon, not a URL) becomes ``provider/model_id``.
    - A bare model id (no separator) defaults to ``openai/<id>``.
    """
    s = spec.strip()
    if not s:
        return "openai/gpt-4o-mini"
    if s.lower().startswith("http://") or s.lower().startswith("https://"):
        return s
    if ":" in s:
        left, right = s.split(":", 1)
        if left and right and "/" not in left:
            return f"{left}/{right}"
        return s
    if "/" in s:
        return s
    return f"openai/{s}"


def build_chat_model() -> Model:
    """Instantiate LiteLLM-backed model from ``CHAT_MODEL`` (default ``openai/gpt-4o-mini``)."""
    raw = os.environ.get("CHAT_MODEL", "openai/gpt-4o-mini")
    model_id = normalize_litellm_model_id(raw)
    return LiteLLMModel(model_id=model_id)
