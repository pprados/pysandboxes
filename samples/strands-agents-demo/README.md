# Strands Agents demo (`strands-agents-demo`)

Console demo of the [Strands Agents](https://strandsagents.com/) SDK: an `Agent` runs the built-in event loop (model → tool calls → tool results → model …) with two tools, **`fetch_webpage`** and **`evaluate_expression`**.

The default user task **requires** both tools: fetch `https://www.google.com`, report how many words its title contains, then compute that count squared. Tool calls are chosen by the model via Strands’ `@tool` registration — the CLI does not invoke the tools directly.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around the agent call) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- API keys for the provider you select with `CHAT_MODEL` (LiteLLM reads the usual provider env vars, e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).

## Setup

```bash
cd samples/strands-agents-demo
make init
cp env.example .env   # optional: edit keys and CHAT_MODEL
```

## Model selection (`CHAT_MODEL`)

The demo uses Strands **`LiteLLMModel`**, so the value follows [LiteLLM](https://docs.litellm.ai/docs/providers) **`provider/model`** ids.

You may also use **`provider:model`**; it is normalized to **`provider/model`** before creating the model.

Examples:

- `openai/gpt-4o-mini` or `openai:gpt-4o-mini`
- `anthropic/claude-3-5-sonnet-20241022`
- `gemini/gemini-2.0-flash` (with `GOOGLE_API_KEY` / GenAI setup as required by LiteLLM)

Default if unset: `openai/gpt-4o-mini`.

## Run

```bash
uv run strands-agents-demo
# or
uv run python -m strands_agents_demo.main
```

Options:

- `--task` — override the user message (should still force tool use).
- `--max-iterations` — cap on **model invocations** per run (default `12`, or `AGENT_MAX_ITERATIONS`).
- `-v` — INFO logging and Strands `PrintingCallbackHandler` (tool names on stdout).

## Dependencies (providers)

`pyproject.toml` pulls **`strands-agents`** extras: `litellm`, `anthropic`, `gemini`, `mistral`, `llamaapi`, plus **`ollama`** for local models via LiteLLM. Many other providers are available through LiteLLM without extra Strands extras; see LiteLLM docs.

## Tests / validation

No network or real LLM keys required for CI:

```bash
make validate
```

From the repo root (same as other samples):

```bash
./samples/test.sh strands-agents-demo
```

## Security note

The expression tool is a plain `eval()`. What confines it is **pysandboxes**, armed from the
profiles above -- not any check inside the tool. Never run learning mode on untrusted code, and
look hard at any `ALLOW:process-exec` rule a learned profile contains before keeping it.
