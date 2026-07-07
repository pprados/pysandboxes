# autogen-demo

Console demo of [Microsoft AutoGen](https://github.com/microsoft/autogen) **AgentChat** with two tools—**`fetch_webpage`** and **`evaluate_expression`**—driven by the model’s tool calls (not hard-coded script logic).

The default task **requires** both tools: it asks the model to fetch `https://www.google.com`, report how many words its title contains, then compute that count squared.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__`—which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit.

Both tools are coroutines, AutoGen's own idiom, and `@sandbox` supports them. The partial mode
is armed with `pysandboxes.run()`, the asynchronous entry point: it arms the profile *and*
binds the sandbox loop, which `async with sandboxes(...)` alone does not do.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`pysandboxes.run()` around the session) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- API credentials for your chosen provider (see below)

## Setup

```bash
cd samples/autogen-demo
make init
cp env.example .env   # optional: edit keys and CHAT_MODEL
```

## Model configuration (`CHAT_MODEL`)

Set **`CHAT_MODEL`** to **`provider:model_id`** or **`provider/model_id`** (both are accepted). The code normalizes slash form to colon before selecting a client.

| Provider       | Example `CHAT_MODEL`              | Auth / notes |
|----------------|-----------------------------------|--------------|
| `openai`       | `openai:gpt-4o-mini`              | `OPENAI_API_KEY` |
| `anthropic`    | `anthropic:claude-3-7-sonnet-20250219` | `ANTHROPIC_API_KEY` |
| `ollama`       | `ollama:llama3.2`                 | Local server (default `http://127.0.0.1:11434`) |
| `google_genai` or `gemini` | `google_genai:gemini-2.0-flash` | `GOOGLE_API_KEY` (Gemini [OpenAI-compatible endpoint](https://ai.google.dev/gemini-api/docs/openai)) |

Default if unset: `openai:gpt-4o-mini`.

Other backends (Azure OpenAI, Semantic Kernel adapters, etc.) are supported by **autogen-ext**; this sample wires the providers above in `autogen_demo/model_client.py`. Extend that module if you need Azure or SK-based clients.

## Run

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. History is the `AssistantAgent`'s own model context: one agent instance serves the whole conversation and carries its state from `run()` to `run()`.

```bash
make run
# or, without make:
set -a && source .env && set +a
autogen-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
autogen-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-tool-iterations` — cap on tool rounds, maps to `AssistantAgent`'s own limit.
- `-v` / `--verbose` — stream AgentChat console output.


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

```bash
make tests
# or
make validate   # lint + tests (no network, no API keys)
```

## Layout

- `autogen_demo/tools.py` — `fetch_webpage`, `evaluate_expression`, each `@sandbox`ed behind a wrapper
- `learn.py` — relearns either profile, in its own mode
- `autogen_demo/model_client.py` — `CHAT_MODEL` → `ChatCompletionClient`
- `autogen_demo/run.py` — `AssistantAgent` + `run_stream` + tool routing
- `autogen_demo/main.py` — CLI, arms the partial profile around the session

**Runtime dependencies:** `pysandboxes` (in-tree at the repository root), `httpx`,
`markdownify`.
