# Pydantic AI demo (`pydantic-ai-demo`)

Console **agent** using [Pydantic AI](https://ai.pydantic.dev/): a chat model with **`fetch_webpage`** and **`evaluate_expression`** registered as tools. The framework runs the **model ↔ tools** loop internally (`run_sync`); this sample caps **model requests** with **`UsageLimits(request_limit=…)`** so runs cannot spin forever.

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
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around `run_sync()`) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
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

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. History is passed as `message_history=` and read back with `result.all_messages()`, which is Pydantic AI's own mechanism.

```bash
make run
# or, without make:
set -a && source .env && set +a
pydantic-ai-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
pydantic-ai-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-iterations` — cap on **model requests** (maps to `UsageLimits.request_limit`; default 15).
- `-v` / `--verbose` — set logging to INFO.

## Relearn the profiles

```bash
make learn
```

It learns each mode in its own mode, into its own file. Read `learn.py` first: learning
only ever **adds**, it writes only when it observed something the profile did not already
allow, it must **never** run on untrusted code, and every `net=` rule it writes needs review --
which hosts a tool may reach is the author's decision, not an observation. Any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being
kept.

To shrink a profile, trim it by hand down to its header and its `net=` rules, then relearn.

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
| `pydantic_ai_demo/tools.py` | `fetch_webpage`, `evaluate_expression`, each `@sandbox`ed behind a wrapper |
| `learn.py` | relearns either profile, in its own mode |
| `pydantic_ai_demo/agent_factory.py` | `build_agent` — `Agent` + `@agent.tool_plain` registration |
| `pydantic_ai_demo/main.py` | CLI, `CHAT_MODEL`, `run_sync` + `UsageLimits` |

## `pyproject.toml` and providers

Runtime dependencies use **`pydantic-ai-slim`** with **multiple optional groups** (OpenAI, Anthropic, Google, Groq, Mistral, Cohere, Bedrock, Hugging Face, Vertex, etc.) so you can switch `CHAT_MODEL` without ad-hoc installs. If an optional group conflicts with your environment, trim it locally and note the change in a comment.
