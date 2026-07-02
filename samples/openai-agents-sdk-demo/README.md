# OpenAI Agents SDK demo

Console demo using the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`): an agent with two **function tools** — `fetch_webpage` and `evaluate_expression` — driven by the model through the SDK’s **`Runner`** (tool loop until a final answer or `max_turns`).

The default task **requires** both tools: fetch `https://www.google.com`, report how many words its title contains, then compute that count squared.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`pysandboxes.run()` around the `Runner`) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

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
