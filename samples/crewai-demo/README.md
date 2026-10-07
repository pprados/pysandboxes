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

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. `Crew.kickoff()` is one-shot by design, so unlike a chat-native framework CrewAI needs an explicit mechanism: the turns are handed back through `kickoff(inputs=...)`.

```bash
make run
# or, without make:
set -a && source .env && set +a
crewai-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
crewai-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-iterations` — maps to the agent’s `max_iter` (default 12, or `AGENT_MAX_ITER`).
- `-v` / `--verbose` — CrewAI verbose output.

## Tool-only scenario

The default task asks the model to fetch `https://www.google.com`, report how many words its title contains, then compute that count squared with **`evaluate_expression`**. It should not succeed without tools.

## Security note

The expression tool is a plain `eval()`. What confines it is **pysandboxes**, armed from the profiles above, not any check inside the tool.

## Relearn the profiles

```bash
make learn FORCE=1
```

The guard is deliberate: this sample's `env=` allowlist was filtered by hand, and learning
only ever **adds**, so an unguarded relearn would silently restore every variable litellm
probes for -- several hundred of them.

Otherwise it learns each mode in its own mode, into its own file. Read `learn.py` first:
learning writes only when it observed something the profile did not already allow, it must
**never** run on untrusted code, and every `net=` rule it writes needs review -- which hosts a
tool may reach is the author's decision, not an observation. Any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being
kept.

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
