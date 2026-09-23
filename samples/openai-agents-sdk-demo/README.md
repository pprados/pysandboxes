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

The SDK defaults to OpenAI when you pass a bare model name. The sample only targets OpenAI:
the SDK's `[litellm]` extra, which routes other providers, is not installed, because the
LiteLLM release it resolved to carried known vulnerabilities.

| Form | Resolved model id | Notes |
|------|---------------------|--------|
| *(empty)* | `gpt-4o-mini` | Default |
| `gpt-4o-mini` | `gpt-4o-mini` | OpenAI |
| `openai:gpt-4o-mini` or `openai/gpt-4o-mini` | `gpt-4o-mini` | OpenAI |

Set `OPENAI_API_KEY`.

Tracing to the OpenAI dashboard is **disabled** when `OPENAI_API_KEY` is unset (avoids trace upload 401s). See the SDK [tracing docs](https://openai.github.io/openai-agents-python/tracing/) to enable or customize.

## Run

`make run` drops you into an interactive chat with the agent. The sandbox is entered
once, around the whole conversation: `@sandbox` needs a running daemon at call time, and a
context manager opened per turn would pay the daemon's startup on every one. History is `result.to_input_list()`, which replays a run as input items for the next one -- the SDK's own mechanism.

```bash
make run
# or, without make:
set -a && source .env && set +a
openai-agents-sdk-demo
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an
expression that tries to escape: the tool answers with the rule that refused it.

Passing `--task` runs a single task and exits instead:

```bash
openai-agents-sdk-demo --task "compute 2*(3+4) with evaluate_expression"
```

Options:

- `--task` — run one task and exit. Omitted: interactive chat.
- `--max-turns` — cap on agent turns, passed to `Runner.run`.
- `-v` / `--verbose` — log at INFO level.


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
```

CI-friendly: **no** live LLM calls or network; tools and runner are mocked.

## Validate (lint + tests)

```bash
make validate
```

From the repo root: `./samples/test.sh openai-agents-sdk-demo`.
