# google-adk-demo

Console demo of [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) with a **tool-calling** agent: **`fetch_webpage`** and **`evaluate_expression`**.

The default user task **requires** both tools: it asks the model to fetch `https://www.google.com`, report how many words its title contains, then compute that count squared.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around the runner) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- API credentials for the model you select (see below)

## Setup

```bash
cd samples/google-adk-demo
make init
```

Optional: copy `env.example` to `.env` and fill in keys.

## Model selection (`CHAT_MODEL`)

ADK is optimized for **Gemini**. You can use:

1. **Native Gemini** (Google AI): set a **bare model id** (no `:` or `/` in the value), for example:

   - `CHAT_MODEL=gemini-2.0-flash`

   Set **`GOOGLE_API_KEY`** (see [Google AI Studio](https://aistudio.google.com/app/apikey)).

2. **LiteLLM connector** (many providers): set a **`provider/model`** or **`provider:model`** string (the second form is normalized to the first):

   - `CHAT_MODEL=openai/gpt-4o-mini` or `CHAT_MODEL=openai:gpt-4o-mini` → requires **`OPENAI_API_KEY`**
   - `CHAT_MODEL=anthropic/claude-3-5-haiku-20241022` → **`ANTHROPIC_API_KEY`**
   - LangChain-style alias: `CHAT_MODEL=google_genai:gemini-2.0-flash` → normalized to **`gemini/gemini-2.0-flash`** for LiteLLM (see [ADK LiteLLM docs](https://google.github.io/adk-docs/agents/models/litellm/))

Consult [LiteLLM providers](https://docs.litellm.ai/docs/providers) for env var names.

**Tool calling and some providers:** Models must emit tool calls in the format the provider expects. For example, **Groq** may return HTTP 400 with `tool_use_failed` and a message like `attempted to call tool 'fetch_webpage {"url": ...}' which was not in request.tools` when the model emits pseudo-XML such as `<function=fetch_webpage ...></function>` instead of JSON tool calls—this is a model/API limitation, not ADK itself. For reliable tool use in this demo, prefer **native Gemini** (`CHAT_MODEL=gemini-2.0-flash` + `GOOGLE_API_KEY`) or another LiteLLM route known to work with OpenAI-style tools.

## Run

```bash
# Uses .env if present (see make init)
google-adk-demo
# or
uv run google-adk-demo
```

Options:

- `--task "..."` — override the user message (keep it tool-dependent for a meaningful demo).
- `--max-iterations N` — maps to ADK `RunConfig.max_llm_calls` (default `12`).
- `-v` — INFO logging (including tool call names).

## Tests

```bash
make validate
```

Tests use mocks only (no real LLM or network in CI).

## Validate from repo root

```bash
./samples/test.sh google-adk-demo
```
