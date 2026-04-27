# Pydantic AI demo (`pydantic-ai-demo`)

Console **agent** using [Pydantic AI](https://ai.pydantic.dev/): a chat model with **`fetch_webpage`** and **`execute_python`** registered as tools. The framework runs the **model ↔ tools** loop internally (`run_sync`); this sample caps **model requests** with **`UsageLimits(request_limit=…)`** so runs cannot spin forever.

The default task **requires** both tools: it loads `https://www.google.com`, then runs Python on the HTML (for example to count words in the `<title>`). The model must not answer from memory alone.

## Security note

`execute_python` uses a **restricted** namespace for demonstration only. It is **not** an OS-level sandbox. Do not point this demo at untrusted users or secrets.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- API credentials for the provider you select (see below)

## Setup

```bash
cd samples/pydantic-ai-demo
cp env.example .env   # optional: edit keys and CHAT_MODEL
make init
```

## Model selection (`CHAT_MODEL`)

The agent is created with a **model string** understood by Pydantic AI (see [models](https://ai.pydantic.dev/models/)). You can write **`provider:model_id`** or **`provider/model_id`** (first `/` splits provider from model id); the sample normalizes slash form to colon form before constructing the agent.

Examples (colon form; slash is equivalent, e.g. `openai/gpt-4o-mini`):

| `CHAT_MODEL` value | Typical API key env |
|--------------------|---------------------|
| `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic:claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `google-gla:gemini-2.0-flash` | `GOOGLE_API_KEY` |
| `groq:llama-3.3-70b-versatile` | `GROQ_API_KEY` |

Google Generative Language models often use the **`google-gla:`** prefix in Pydantic AI. Other providers are available when the matching **`pydantic-ai-slim[…]`** extra is installed (see `pyproject.toml`).

Default if unset: `openai:gpt-4o-mini`.

## Run

```bash
# Optional: export CHAT_MODEL and provider keys
set -a && source .env && set +a
pydantic-ai-demo
# or
python -m pydantic_ai_demo
```

Options:

- `--task` — override the user message (should still force tool use).
- `--max-iterations` — cap on **model requests** (maps to `UsageLimits.request_limit`; default 15).
- `-v` / `--verbose` — set logging to INFO.

## Tests

No network or real API keys required in CI.

From `samples/pydantic-ai-demo`, use **`make tests`** or **`uv run pytest`** so dependencies resolve from this project’s environment.

Minimal validation from the repo root: **`./samples/test.sh pydantic-ai-demo`** runs `make init` and **`make validate`** (lint + tests) in that directory.

```bash
make init
make validate
```

## Layout

| Path | Role |
|------|------|
| `pydantic_ai_demo/tools.py` | `fetch_webpage`, `execute_python` (plain functions) |
| `pydantic_ai_demo/agent_factory.py` | `build_agent` — `Agent` + `@agent.tool_plain` registration |
| `pydantic_ai_demo/main.py` | CLI, `CHAT_MODEL`, `run_sync` + `UsageLimits` |

## `pyproject.toml` and providers

Runtime dependencies use **`pydantic-ai-slim`** with **multiple optional groups** (OpenAI, Anthropic, Google, Groq, Mistral, Cohere, Bedrock, Hugging Face, Vertex, etc.) so you can switch `CHAT_MODEL` without ad-hoc installs. If an optional group conflicts with your environment, trim it locally and note the change in a comment.
