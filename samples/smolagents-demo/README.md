# Smolagents demo (`smolagents-demo`)

Console demo using Hugging Face [**smolagents**](https://huggingface.co/docs/smolagents/index): a **`ToolCallingAgent`** (JSON tool calls) with **`fetch_webpage`** and **`evaluate_expression`**, backed by **`LiteLLMModel`** so you can point at many providers via [LiteLLM](https://docs.litellm.ai/).

The default task **requires** both tools: it loads `https://www.google.com`, counts the words in its title, then computes that count squared. The model must not answer from memory alone.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around `agent.run()`) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
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

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. `agent.run(task, reset=False)` continues the agent's own memory instead of clearing it, so one agent instance carries the conversation.

```bash
make run
# or, without make:
set -a && source .env && set +a
smolagents-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
smolagents-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-iterations` — cap on agent steps (`max_steps`, default 12).
- `-v` / `--verbose` — smolagents Rich **DEBUG** logs.

## Relearn the profiles

```bash
make learn
```

It learns each mode in its own mode, into its own file. Read `learn.py` first: learning
only ever **adds**, it writes only when it observed something the profile did not already
allow, it must **never** run on untrusted code, and it cannot produce the `net=` rules --
which hosts a tool may reach is the author's decision, not an observation. Any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being
kept.

To shrink a profile, trim it by hand down to its header and its `net=` rules, then relearn.

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
| `smolagents_demo/tools.py` | `fetch_webpage`, `evaluate_expression` (`@tool`), each `@sandbox`ed behind a wrapper |
| `learn.py` | relearns either profile, in its own mode |
| `smolagents_demo/model_builder.py` | `CHAT_MODEL` → `LiteLLMModel` |
| `smolagents_demo/main.py` | CLI, `ToolCallingAgent`, default prompts |

## Relationship to pysandboxes

This sample does **not** import `pysandboxes` or run user code inside the project’s OS sandbox; it is a standalone agent demo. The `[tool.uv.sources]` entry for `pysandboxes` is reserved for future integration.
