# LangGraph demo (`langgraph-demo`)

Console chatbot built with **[LangGraph](https://langchain-ai.github.io/langgraph/)**: a
`StateGraph` that alternates between the model and a `ToolNode`, with **`fetch_webpage`** and
**`evaluate_expression`** as its two tools.

The default task **requires** both tools: it loads `https://www.google.com`, then computes an
expression. The model must not answer from memory alone.

## What the sandbox does here

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__` -- which
is known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`.
That is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit. There is no expression filter here, not even an optional one --
as soon as one exists, the reader can no longer tell who blocked what. In particular the tool
exposes **no math namespace**: `foo + 1` raises `NameError`, and that is the intended answer.
An applicative feature layer around `eval()` is exactly what makes a reader unsure who blocked
what.

`sqrt(144)` answers differently, and the difference is the whole demonstration: the profile
declares `eval-syntax=arith, compare`, which admits no call at all, so the expression is
refused while it is parsed and rewritten -- before Python has to know whether `sqrt` names
anything. The `NameError` shows the application is plain; the refusal shows what pysandboxes
adds on top of it.

Two profiles, one per mode, each learned in its own by `learn.py`:

| Profile | Mode | What is confined |
|---------|------|------------------|
| `.py-sandboxes` | partial | the tool bodies only (`pysandboxes.run()` around the graph) |
| `.py-sandboxes-complete` | complete | the whole process, launched with `python -m pysandboxes.python_sb` |

They are deliberately separate: sharing one file would grant each mode the other's privileges
for nothing, which is the opposite of what the partial mode is for.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- An OpenAI API key (this sample uses `langchain-openai` directly)

## Setup

```bash
cd samples/langgraph-demo
cp env.example .env   # optional: edit OPENAI_API_KEY
make init
```

`OPENAI_BASE_URL` is honoured if set, so an OpenAI-compatible endpoint works too.

## Run

`make run` drops you into an interactive chat. The sandbox is entered once, around the whole
conversation: `@sandbox` needs a running daemon at call time, and a context manager opened per
turn would pay the daemon's startup on every one. History is carried by the graph itself --
each turn sends the accumulated messages into `ainvoke` and keeps what the graph returns,
which is LangGraph's own idiom.

```bash
make run
# or, without make:
langgraph-chat chat
```

Leave with `/quit` or Ctrl-D. Ask for a host the profile does not allow, or for an expression
that tries to escape: the tool answers with the rule that refused it.

The CLI is a click group, so `langgraph-chat` alone only prints help. Its other subcommands
run a single thing and exit, each inside the sandbox:

```bash
langgraph-chat ask "fetch https://www.google.com and count the words in its title"
langgraph-chat calc "2*(3+4)"
langgraph-chat fetch "https://www.google.com"
```

Options: `--model` (default `gpt-4o-mini`) and `--temperature` on `chat` and `ask`.

## Relearn the profiles

```bash
make learn
```

It learns each mode in its own mode, into its own file. Read `learn.py` first: learning only
ever **adds**, it writes only when it observed something the profile did not already allow, it
must **never** run on untrusted code, and every `net=` rule it writes needs review -- which hosts a
tool may reach is the author's decision, not an observation. Any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being kept.

To shrink a profile, trim it by hand down to its header and its `net=` rules, then relearn.

## Tests

No network or real API keys required in CI.

From `samples/langgraph-demo`, use **`make tests`** or **`uv run pytest`** so dependencies
resolve from this project's environment.

```bash
make init
make validate   # lint + tests
```

`tests/test_tools_sandbox.py` carries the corpus's standard suite: a negative control proving
the escape succeeds *without* the sandbox, an allowed host reached, a host outside the rules
refused and read back through `sandbox_denials()`, the expression tool still computing, the
escape confined, the wrapper naming the rule to the model, a whitelist guard run over **both**
profiles, and the same calls confined again in complete mode under `python-sb`.

## Layout

| Path | Role |
|------|------|
| `langgraph_simple_chatbot/tools.py` | `fetch_webpage`, `evaluate_expression` (`@sandbox` + `@tool`) |
| `langgraph_simple_chatbot/agent.py` | the `StateGraph`: model node, `ToolNode`, conditional edge |
| `langgraph_simple_chatbot/console.py` | the interactive chat loop |
| `langgraph_simple_chatbot/cli.py` | click group; each subcommand opens the sandbox |
| `learn.py` | relearns both profiles, one per mode |

## Why the tools are split in two

The sandbox function bridge resolves its target by name, `module:qualname`, and re-imports it
inside the sandbox. A framework decorator replaces the function with an object, which is not
importable that way. So `@sandbox` goes on a module-level `_`-prefixed coroutine and `@tool`
on a thin wrapper that calls it. The wrapper also converts errors: `@sandbox` re-raises, while
a tool has to report to the model as text, naming the rule that refused the call.

## License

Apache V2

## Author

Philippe Prados (pprados)
