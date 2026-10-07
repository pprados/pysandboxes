# LangChain demo (`langchain-demo`)

Console **agent loop** for LangChain 1.x: a chat model with **`fetch_webpage`** and **`evaluate_expression`** bound via `bind_tools`, iterating until the model stops requesting tools or a **maximum iteration** count is reached. This sample is the reference shape the other framework samples follow.

The default task **requires** both tools: it loads `https://www.google.com`, then computes an expression. The model must not answer from memory alone.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__` -- which
is known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`.
That is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit. There is no expression filter here, not even an optional one --
as soon as one exists, the reader can no longer tell who blocked what.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`with sandboxes(...)` around the agent loop) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's
privileges for nothing, which is the opposite of what the partial mode is for.

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

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. History is
LangChain's own message list, which `run_agent_loop` appends to as it goes.

```bash
make run
# or, without make:
set -a && source .env && set +a
langchain-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
langchain-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-iterations` — cap on model+tool rounds (default 12).
- `-v` / `--verbose` — log agent turns and tool invocations.

## Relearn the profiles

```bash
make learn
```

It learns each mode in its own mode, into its own file. Read `learn.py` first: learning
only ever **adds**, it writes only when it observed something the profile did not already
allow, it must **never** run on untrusted code, and every `net=` rule it writes needs review --
which hosts a tool may reach is the author's decision, not an observation. Any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being kept.

To shrink a profile, trim it by hand down to its header and its `net=` rules, then relearn.

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
| `langchain_demo/tools.py` | `fetch_webpage`, `evaluate_expression` (`@sandbox` + `@tool`) |
| `langchain_demo/chain.py` | `run_agent_loop` (`bind_tools` + `ToolMessage` loop) |
| `langchain_demo/main.py` | CLI, interactive `chat()`, `init_chat_model`, default prompts |
| `learn.py` | relearns both profiles, one per mode |

## `pyproject.toml` and LLM packages

Runtime dependencies include the official LangChain chat integrations for **many** providers plus **`langchain-litellm`**, so you can switch `CHAT_MODEL` without reinstalling a separate extra. If a package is ever removed from the repo or PyPI, it will be noted in a comment in `pyproject.toml` or here.
