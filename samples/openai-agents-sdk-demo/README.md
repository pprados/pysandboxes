# OpenAI Agents SDK demo

Console demo using the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`): an agent with two **function tools** — HTTP fetch and restricted Python execution — driven by the model through the SDK’s **`Runner`** (tool loop until a final answer or `max_turns`).

The default task **requires** both tools: fetch `https://www.google.com`, then run Python on the returned HTML to analyze the `<title>`.

**Security:** `execute_python` is a **demo** (restricted `exec` in-process). It is **not** an OS-level sandbox.

## Setup

From this directory:

```bash
make init
```

Optional: `cp env.example .env` and set API keys.

## Model selection (`CHAT_MODEL`)

The SDK defaults to OpenAI when you pass a bare model name. This sample also supports **LiteLLM-routed** ids via the `litellm/` prefix (requires the `[litellm]` extra, already in dependencies).

Accepts **both** `:` and `/` where noted below.

| Form | Resolved model id | Notes |
|------|---------------------|--------|
| *(empty)* | `gpt-4o-mini` | Default |
| `gpt-4o-mini` | `gpt-4o-mini` | OpenAI |
| `openai:gpt-4o-mini` or `openai/gpt-4o-mini` | `gpt-4o-mini` | OpenAI |
| `litellm:anthropic/claude-sonnet-4-20250514` | `litellm/anthropic/claude-sonnet-4-20250514` | LiteLLM |
| `anthropic/claude-sonnet-4-20250514` | `litellm/anthropic/claude-sonnet-4-20250514` | Non-OpenAI providers |
| `litellm/openrouter/openai/gpt-4o-mini` | unchanged | Example OpenRouter via LiteLLM |

Set the API keys your route expects (`OPENAI_API_KEY` for OpenAI, `ANTHROPIC_API_KEY` for Anthropic via LiteLLM, etc.).

Tracing to the OpenAI dashboard is **disabled** when `OPENAI_API_KEY` is unset (avoids trace upload 401s for LiteLLM-only setups). See the SDK [tracing docs](https://openai.github.io/openai-agents-python/tracing/) to enable or customize.

## Run

```bash
# Uses CHAT_MODEL and OPENAI_API_KEY from the environment (or .env)
openai-agents-sdk-demo

# Or
uv run openai-agents-sdk-demo -- -v

# Custom task / turn cap
uv run openai-agents-sdk-demo -- --task "Your tool-only task mentioning https://www.google.com" --max-turns 15
```

## Tests

```bash
make tests
```

CI-friendly: **no** live LLM calls or network; tools and runner are mocked.

## Validate (lint + tests)

```bash
make validate
```

From the repo root: `./samples/test.sh openai-agents-sdk-demo`.
