# crewai-demo

Console demo of a **CrewAI** agent with two tools—**`fetch_webpage`** and
**`evaluate_expression`**—driven by the model’s tool calls.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around `crew.kickoff()`) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Setup

```bash
cd samples/crewai-demo
cp env.example .env
# Edit .env: set CHAT_MODEL and the API key(s) for your provider.
uv sync --group dev --group test
```

## Model and providers

Configure the chat model with **`CHAT_MODEL`** using CrewAI’s **`provider/model`** form (aligned with LiteLLM). A single **`provider:model`** form is also accepted and normalized to slashes. For example:

- `openai/gpt-4o-mini`
- `anthropic/claude-sonnet-4-20250514`
- `gemini/gemini-2.0-flash` (when using Google via installed extras)

This project depends on **`crewai`** with extras **`anthropic`**, **`aws`**, **`azure-ai-inference`**, **`bedrock`**, **`google-genai`**, and **`litellm`** so common native and LiteLLM-backed backends resolve in one lockfile. Install additional keys only for providers you use.

See also: [CrewAI LLMs](https://docs.crewai.com/concepts/llms).

## Run

```bash
# Optional: source .env for keys
set -a && source .env && set +a
uv run crewai-demo
# or
uv run python -m crewai_demo
```

Options:

- `--task` — override the user task (the default **requires** `fetch_webpage` and `evaluate_expression` on `https://www.google.com`).
- `--max-iterations` — maps to the agent’s `max_iter` (default 12, or `AGENT_MAX_ITER`).
- `-v` / `--verbose` — CrewAI verbose output.

## Tool-only scenario

The default task asks the model to fetch `https://www.google.com`, report how many words its title contains, then compute that count squared with **`evaluate_expression`**. It should not succeed without tools.

## Security note

The expression tool is a plain `eval()`. What confines it is **pysandboxes**, armed from the profiles above, not any check inside the tool.

## Tests

```bash
make init
make validate
# or: make tests
```

From the repo root, **`./samples/test.sh crewai-demo`** runs `make init` and `make validate` in this folder.

Tests mock HTTP and avoid live LLM calls in CI.

## Layout

- `crewai_demo/tools.py` — `fetch_webpage` and `evaluate_expression` via `crewai.tools.tool`, each `@sandbox`ed behind a wrapper
- `learn.py` — relearns either profile, in its own mode
- `crewai_demo/main.py` — `LLM` from env, `Agent` + `Task` + `Crew`, `kickoff()`
