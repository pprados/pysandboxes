"""Resolve ``CHAT_MODEL`` into model ids understood by the OpenAI Agents SDK."""

from __future__ import annotations


def normalize_chat_model_spec(spec: str) -> str:
    """Normalize user ``CHAT_MODEL`` for ``Agent(model=...)``.

    - Bare id (e.g. ``gpt-4o-mini``): OpenAI model name with the default provider.
    - ``openai:...`` or ``openai/...``: strip the ``openai`` prefix (SDK default is OpenAI).
    - ``litellm:...`` or ``litellm/...``: LiteLLM-routed id (``litellm/...`` per SDK examples).
    - ``provider/model`` (e.g. ``anthropic/claude-...``): prefix with ``litellm/`` for LiteLLM routing.

    Both ``:`` and ``/`` separators are accepted where documented in the README.
    """
    s = spec.strip()
    if not s:
        return "gpt-4o-mini"
    sl = s.lower()
    if sl.startswith("litellm:"):
        return "litellm/" + s.split(":", 1)[1].lstrip("/")
    if sl.startswith("litellm/"):
        return s
    if sl.startswith("openai:"):
        return s.split(":", 1)[1].strip()
    if "/" in s:
        left, right = s.split("/", 1)
        ll = left.lower()
        if ll in ("http:", "https:"):
            return s
        if ll == "openai" and right:
            return right
        return f"litellm/{s}"
    return s
