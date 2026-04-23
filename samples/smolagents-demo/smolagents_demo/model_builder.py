"""Build ``LiteLLMModel`` from ``CHAT_MODEL`` (multi-provider via LiteLLM)."""

import os

from smolagents import LiteLLMModel


def normalize_lite_llm_model_id(spec: str) -> str:
    """Normalize ``CHAT_MODEL`` to LiteLLM ``provider/model`` form.

    - Already contains ``/`` (and not a URL): returned unchanged.
    - ``provider:model_id`` (single colon, not ``http``): becomes ``provider/model_id``.
    - Bare model id or other forms: returned unchanged for LiteLLM to interpret.
    """
    s = spec.strip()
    if not s:
        return "openai/gpt-4o-mini"
    if s.lower().startswith("http"):
        return s
    if "/" in s:
        return s
    if ":" in s:
        left, right = s.split(":", 1)
        if left and right:
            return f"{left}/{right}"
    return s


def build_model_from_env() -> LiteLLMModel:
    """Instantiate ``LiteLLMModel`` from ``CHAT_MODEL``."""
    raw = os.environ.get("CHAT_MODEL", "openai/gpt-4o-mini")
    model_id = normalize_lite_llm_model_id(raw)
    return LiteLLMModel(model_id=model_id)
