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

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. One `Agent` instance serves the whole conversation and its own `agent.messages` accumulates the turns.

```bash
make run
# or, without make:
set -a && source .env && set +a
strands-agents-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
strands-agents-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-iterations` — cap on **model invocations** per run (default `12`, or `AGENT_MAX_ITERATIONS`).
- `-v` — INFO logging and Strands `PrintingCallbackHandler` (tool names on stdout).

## Dependencies (providers)

`pyproject.toml` pulls **`strands-agents`** extras: `litellm`, `anthropic`, `gemini`, `mistral`, `llamaapi`, plus **`ollama`** for local models via LiteLLM. Many other providers are available through LiteLLM without extra Strands extras; see LiteLLM docs.

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
