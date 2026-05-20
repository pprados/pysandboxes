# crewai-demo

Console demo of a **CrewAI** agent with two tools—**HTTP fetch** and **restricted Python execution**—driven by the model’s tool calls. There is **no** `pysandboxes` integration in this sample (no sandbox daemon or guards).

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

- `--task` — override the user task (the default **requires** `fetch_webpage` and `execute_python` on `https://www.google.com`).
- `--max-iterations` — maps to the agent’s `max_iter` (default 12, or `AGENT_MAX_ITER`).
- `-v` / `--verbose` — CrewAI verbose output.

## Tool-only scenario

The default task asks the model to fetch `https://www.google.com`, parse the HTML with **`execute_python`**, and report the word count of the first `<title>` text. It should not succeed without tools.

## Security note

**`execute_python`** runs code in a restricted namespace for **demonstration only**. It is **not** an OS-level sandbox. Do not expose it to untrusted users.

## Tests

```bash
make init
make validate
# or: make tests
```

From the repo root, **`./samples/test.sh crewai-demo`** runs `make init` and `make validate` in this folder.

Tests mock HTTP and avoid live LLM calls in CI.

## Layout

- `crewai_demo/tools.py` — `fetch_webpage` and `execute_python` via `crewai.tools.tool`
- `crewai_demo/main.py` — `LLM` from env, `Agent` + `Task` + `Crew`, `kickoff()`
