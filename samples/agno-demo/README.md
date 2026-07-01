# Agno demo (`agno-demo`)

Console demo for **[Agno](https://www.agno.com/)**: an `Agent` with **`fetch_webpage`** and **`evaluate_expression`** as tools. Agno runs the **model ↔ tool** loop internally; `tool_call_limit` caps how many tool invocations are allowed in one run.

The default task **requires** both tools: it loads `https://www.google.com`, counts the words in its title, then computes that count squared. The model must not answer from memory alone.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__` -- which
is known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`.
That is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around `agent.run()`) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's
privileges for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- API credentials for the provider you select (see below)

## Setup

```bash
cd samples/agno-demo
cp env.example .env   # optional: edit keys and CHAT_MODEL
make init
```

## Model selection (`CHAT_MODEL`)

Agno expects **`provider:model_id`** (see `agno.models.utils._parse_model_string`). This demo also accepts **`provider/model_id`** when there is no `:` in the value: the first `/` is turned into `:` so you can reuse the same style as other samples.

Examples:

| `CHAT_MODEL` value | Typical API key env |
|--------------------|---------------------|
| `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic:claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `google:gemini-2.0-flash` | `GOOGLE_API_KEY` |
| `groq:llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `ollama:llama3.1` | (local; optional `OLLAMA_HOST`) |
| `litellm:openai/gpt-4o-mini` | (via LiteLLM; see [LiteLLM docs](https://docs.litellm.ai/docs/)) |

Provider ids match Agno’s registry (e.g. `mistral`, `cohere`, `aws-bedrock`, `xai`, `perplexity`, `fireworks`, `together`, `deepseek`, …). Default if unset: `openai:gpt-4o-mini`.

Runtime dependencies include the common SDKs Agno uses for those integrations (`openai`, `anthropic`, `google-genai`, `groq`, `cohere`, `mistralai`, `boto3`, `litellm`, `ollama`, `huggingface_hub`, …). Add or pin extras locally if you need a provider not listed.

## Run

```bash
set -a && source .env && set +a
agno-demo
# or
python -m agno_demo
```

Options:

- `--task` — override the user message (should still force tool use).
- `--max-tool-calls` — cap tool invocations per run (default 32; env `AGENT_MAX_TOOL_CALLS`).
- `-v` / `--verbose` — more logging.

## Tests

No network or real API keys required in CI.

From `samples/agno-demo`, use **`make tests`** or **`uv run pytest`** so dependencies resolve from this project’s environment.

Minimal validation from the repo root: **`./samples/test.sh agno-demo`** runs `make init` and **`make validate`** in this directory.

```bash
make init
make validate
```

## Layout

| Path | Role |
|------|------|
| `agno_demo/tools.py` | `fetch_webpage`, `evaluate_expression`, each `@sandbox`ed behind a wrapper |
| `learn.py` | relearns either profile, in its own mode |
| `agno_demo/main.py` | CLI, `CHAT_MODEL` normalization, `Agent` construction |
