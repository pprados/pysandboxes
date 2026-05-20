# LangChain demo (`langchain-demo`)

Console **agent loop** for LangChain 1.x: a chat model with **`fetch_webpage`** and **`execute_python`** bound via `bind_tools`, iterating until the model stops requesting tools or a **maximum iteration** count is reached.

The default task **requires** both tools: it loads `https://www.google.com`, then runs Python on the HTML (for example to measure words in the `<title>`). The model must not answer from memory alone.

## Security note

`execute_python` uses a **restricted** namespace for demonstration only. It is **not** an OS-level sandbox. Do not point this demo at untrusted users or secrets.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- API credentials for the provider you select (see below)

## Setup

```bash
cd samples/langchain-demo
cp env.example .env   # optional: edit keys and CHAT_MODEL
make init
```

## Model selection (`CHAT_MODEL`)

The chat model is created with LangChain’s **`init_chat_model`** using a single specifier string. You can write **`provider:model_id`** or **`provider/model_id`** (first `/` splits provider from model).

Examples (colon form; slash is equivalent, e.g. `openai/gpt-4o-mini`):

| `CHAT_MODEL` value | Typical API key env |
|--------------------|---------------------|
| `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic:claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `google_genai:gemini-2.0-flash` | `GOOGLE_API_KEY` |
| `ollama:llama3.1` | (local; no cloud key) |

Other providers installed in this sample (see `pyproject.toml`) follow the same pattern where supported by `init_chat_model` and the integration package. **LiteLLM** is available via `langchain-litellm` for additional backends.

Default if unset: `openai:gpt-4o-mini`.

## Run

```bash
# Optional: export CHAT_MODEL and provider keys
set -a && source .env && set +a
langchain-demo
# or
python -m langchain_demo
```

Options:

- `--task` — override the user message (should still force tool use).
- `--max-iterations` — cap (default 12).
- `-v` / `--verbose` — log agent turns and tool invocations.

## Tests

No network or real API keys required in CI.

From `samples/langchain-demo`, use **`make tests`** or **`uv run pytest`** so dependencies resolve from this project’s environment. Running plain **`pytest`** with whatever Python is first on your `PATH` often fails with `ModuleNotFoundError: No module named 'langchain_core'`.

Minimal validation (same as the create-sample skill): from the repo root, **`./samples/test.sh langchain-demo`** runs `make init` and **`make validate`** (lint + tests) in that directory.

```bash
make init
make validate
# or: make tests
# or: uv run pytest -v tests
```

## Layout

| Path | Role |
|------|------|
| `langchain_demo/tools.py` | `fetch_webpage`, `execute_python` (`@tool`) |
| `langchain_demo/chain.py` | `run_agent_loop` (`bind_tools` + `ToolMessage` loop) |
| `langchain_demo/main.py` | CLI, `init_chat_model`, default prompts |

## `pyproject.toml` and LLM packages

Runtime dependencies include the official LangChain chat integrations for **many** providers plus **`langchain-litellm`**, so you can switch `CHAT_MODEL` without reinstalling a separate extra. If a package is ever removed from the repo or PyPI, it will be noted in a comment in `pyproject.toml` or here.
