"""Resolve ``CHAT_MODEL`` into model ids understood by the OpenAI Agents SDK."""

from __future__ import annotations


def normalize_chat_model_spec(spec: str) -> str:
    """Normalize user ``CHAT_MODEL`` for ``Agent(model=...)``.

    - Bare id (e.g. ``gpt-4o-mini``): OpenAI model name with the default provider.
    - ``openai:...`` or ``openai/...``: strip the ``openai`` prefix (SDK default is OpenAI).

    Any other id is passed through unchanged.
    """
    s = spec.strip()
    if not s:
        return "gpt-4o-mini"
    sl = s.lower()
    if sl.startswith("openai:"):
        return s.split(":", 1)[1].strip()
    if sl.startswith("openai/") and len(s) > len("openai/"):
        return s.split("/", 1)[1]
    return s
