# Smolagents demo (`smolagents-demo`)

Console demo using Hugging Face [**smolagents**](https://huggingface.co/docs/smolagents/index): a **`ToolCallingAgent`** (JSON tool calls) with **`fetch_webpage`** and **`execute_python`**, backed by **`LiteLLMModel`** so you can point at many providers via [LiteLLM](https://docs.litellm.ai/).

The default task **requires** both tools: it loads `https://www.google.com`, then runs Python on the HTML (for example to count words in the `<title>`). The model must not answer from memory alone.

## Security note

`execute_python` uses a **restricted** namespace for demonstration only. It is **not** an OS-level sandbox. Do not expose this demo to untrusted users or secrets.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- API credentials for the provider you select (see below)

## Setup

```bash
cd samples/smolagents-demo
cp env.example .env   # optional: edit keys and CHAT_MODEL
make init
```

## Model selection (`CHAT_MODEL`)

The chat model is built with **`LiteLLMModel`** from smolagents. LiteLLM expects a **`provider/model`** string (e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-5-sonnet-latest`). You may also write **`provider:model`**; the demo normalizes a single colon to a slash when the value is not a URL.

Examples:

| `CHAT_MODEL` value | Typical API key env |
|--------------------|---------------------|
| `openai/gpt-4o-mini` or `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic/claude-3-5-sonnet-latest` | `ANTHROPIC_API_KEY` |
| `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` (see LiteLLM docs for the provider) |

Additional backends are available through LiteLLM; see the [LiteLLM provider list](https://docs.litellm.ai/docs/providers).

Default if unset: `openai/gpt-4o-mini`.

This sample includes **`smolagents[litellm,openai]`** so LiteLLM and the OpenAI SDK are installed by default. Other providers may need extra client libraries per LiteLLM’s documentation.

## Run

```bash
# Optional: export CHAT_MODEL and provider keys
set -a && source .env && set +a
smolagents-demo
# or
python -m smolagents_demo
```

Options:

- `--task` — override the user message (should still force tool use).
- `--max-iterations` — cap on agent steps (`max_steps`, default 12).
- `-v` / `--verbose` — smolagents Rich **DEBUG** logs.

## Tests

No network or real API keys required in CI.

From `samples/smolagents-demo`, use **`make tests`** or **`uv run pytest`** so dependencies resolve from this project’s environment.

Minimal validation (same as the create-sample skill): from the repo root, **`./samples/test.sh smolagents-demo`** runs `make init` and **`make validate`** (lint + tests) in that directory.

```bash
make init
make validate
# or: make tests
# or: uv run pytest -v tests
```

## Layout

| Path | Role |
|------|------|
| `smolagents_demo/tools.py` | `fetch_webpage`, `execute_python` (`@tool`) |
| `smolagents_demo/model_builder.py` | `CHAT_MODEL` → `LiteLLMModel` |
| `smolagents_demo/main.py` | CLI, `ToolCallingAgent`, default prompts |

## Relationship to pysandboxes

This sample does **not** import `pysandboxes` or run user code inside the project’s OS sandbox; it is a standalone agent demo. The `[tool.uv.sources]` entry for `pysandboxes` is reserved for future integration.
