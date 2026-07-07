# Samples

We offer several scenarios for using **Py-Sandboxes**, combined with different frameworks.

Every sample under [`samples/`](../samples/) demonstrates the same scenario, so that what
changes from one to the next is only the framework's own way of declaring and dispatching a
tool. A chat agent is given exactly two tools:

- **`fetch_webpage`** fetches a URL and returns it as markdown — it shows that pysandboxes
  controls which hosts a tool may reach;
- **`evaluate_expression`** receives a "python like" expression and computes it — it shows
  that pysandboxes confines malicious code arriving through a tool's argument.

Neither tool is written defensively. `fetch_webpage` calls httpx with whatever URL it is
given, and `evaluate_expression` is a plain `eval()` with an emptied `__builtins__` — which is
known not to hold, since `().__class__.__base__.__subclasses__()` still reaches `Popen`. That
is deliberate: whatever refuses a host or an escape is **pysandboxes**, and no applicative
filter can take the credit. There is deliberately **no expression filter**, not even an
optional one: as soon as one exists, the reader can no longer tell who blocked what.

## The two modes, and the two profiles

Each sample can be run two ways, and carries **one profile per mode**:

| Profile | Mode | What is confined | How it is launched |
|---------|------|------------------|--------------------|
| `.py-sandboxes` | partial | the tool bodies only | the application opens `with sandboxes(...)` or `pysandboxes.run(...)` itself |
| `.py-sandboxes-complete` | complete | the whole process | `python -m pysandboxes.python_sb` in front of the application |

The two files are deliberately separate. Sharing one would grant each mode the other's
privileges for nothing, which is the opposite of what the partial mode is for. Each is learned
in its own mode, by the sample's own `learn.py` — see `make learn`.

Counter-intuitively the **partial** profile is usually the larger one: in partial mode the SSE
bridge that carries the calls into the sandboxed child (fastapi, uvicorn, starlette,
websockets…) runs inside that child, next to the tool, and is therefore charged to the
profile. The complete mode takes another path and never starts that server. So the privilege
reduction of the partial mode does not show up in the number of rules but in the **perimeter
of confined code**. It also gives a free measuring instrument: rules present in the complete
profile come from the application, rules present only in the partial one come from the
transport.

## Why every sample splits its tools in two

The sandbox function bridge resolves its target by name, `module:qualname`, and re-imports it
inside the sandbox. A framework decorator replaces the function with an object
(`StructuredTool`, `SimpleTool`, `Tool`, `DecoratedFunctionTool`…), which is not importable
that way. So `@sandbox` goes on a module-level `_`-prefixed function and the framework's own
decorator on a thin wrapper that calls it.

The wrapper also converts errors. `@sandbox` re-raises, while a tool has to report to the
model as text: without that conversion httpx rewrites a refused connection into
"All connection attempts failed" and the model cannot tell a rule from an outage. Each wrapper
therefore names the rule, read from `sandbox_denials()`.

## Running a sample

Each sample is self-contained: its own `uv` environment, its own `Makefile`, its own
documentation.

```bash
cd samples/langchain-demo
make init      # uv sync
make run       # interactive chat with the framework's agent
make tests     # the sample's own suite
make lint      # mypy + black + ruff
make learn     # relearn both profiles, one per mode
```

`make run` drops you into a chat. Ask for a host the profile does not allow, or for an
expression that tries to escape, and the tool answers with the rule that refused it. The
sandbox is entered once, around the whole conversation: `@sandbox` needs a running daemon at
call time, and a context manager opened per turn would pay the daemon's startup on every one.

**`make learn` must never be run on untrusted code**, and any
`python-api=ALLOW:process-exec` a learning run produces deserves a hard look before being
kept. Learning only ever *adds*, it writes only when it observed something the profile did not
already allow, and it cannot produce the `net=` rules: which hosts a tool may reach is the
author's decision, not an observation.

From the repository root, `make sample-tests` runs every sample's suite.

## MCP

One of the initial goals of the project is to enhance security when using tools with a
language model (LLM).

The [MCP](https://modelcontextprotocol.io/specification/2025-06-18) specification provides
Python APIs to expose tools via this protocol, and to create or connect MCP clients to invoke
these tools ([MCP Client](https://modelcontextprotocol.io/clients)).

### Standard Python MCP API

In this scenario, we will expose an MCP server to be used by generative AI applications.

Depending on the launch command, the MCP server will be more or less isolated from the OS or
the client.

#### MCP Server

The [MCP server](../samples/mcp-server-demo/README.md) sub-project offers different launch
scenarios to isolate the MCP server to a greater or lesser extent: complete or partial mode,
over `stdio` or over `http`. It is where the two tools live, and therefore where their
profiles live. It has no chat of its own — `make run` starts the server, and the conversation
belongs to the client.

#### MCP Client

The [MCP client](../samples/mcp-client-demo/README.md) sub-project offers different launch
scenarios to add sandboxes in an architecture combining an MCP client and an MCP server. Its
`servers_config.json` is a symlink pointing at one of them:

| Configuration | What it demonstrates |
|---------------|----------------------|
| `stdio_no_sandbox.json` | the negative control: no sandbox at all |
| `stdio_sandboxes_partial.json` | the server confines only its tool bodies |
| `stdio_sandboxes_complete.json` | the server runs entirely under `python-sb` |
| `http.json` | client and server in separate sandboxes, over http |

## Agent frameworks

Each of these samples integrates the two tools **following its own framework's approach** —
which is the point of having one per framework rather than a single generic example.

| Sample | Framework | How the tool is declared | How the sandbox is entered | Tests |
|--------|-----------|--------------------------|----------------------------|-------|
| [agno-demo](../samples/agno-demo/README.md) | [Agno](https://www.agno.com/) | plain callables passed to `Agent(tools=...)` | `with sandboxes(...)` | 15 |
| [autogen-demo](../samples/autogen-demo/README.md) | [AutoGen AgentChat](https://microsoft.github.io/autogen/) | coroutines passed to `AssistantAgent` | `pysandboxes.run(...)` | 14 |
| [crewai-demo](../samples/crewai-demo/README.md) | [CrewAI](https://www.crewai.com/) | `@tool` → `Tool.run(**kwargs)` | `with sandboxes(...)` | 11 |
| [google-adk-demo](../samples/google-adk-demo/README.md) | [Google ADK](https://google.github.io/adk-docs/) | plain callables on an `LlmAgent` | `with sandboxes(...)` | 15 |
| [langchain-demo](../samples/langchain-demo/README.md) | [LangChain](https://www.langchain.com/) | `@tool` → `StructuredTool.invoke` | `with sandboxes(...)` | 13 |
| [langgraph-demo](../samples/langgraph-demo/README.md) | [LangGraph](https://langchain-ai.github.io/langgraph/) | `@tool` dispatched by a `ToolNode` | `pysandboxes.run(...)` | 17 |
| [openai-agents-sdk-demo](../samples/openai-agents-sdk-demo/README.md) | [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | `function_tool(fn, name_override=...)` | `pysandboxes.run(...)` | 19 |
| [pydantic-ai-demo](../samples/pydantic-ai-demo/README.md) | [Pydantic AI](https://ai.pydantic.dev/) | plain callables registered on the `Agent` | `with sandboxes(...)` | 13 |
| [smolagents-demo](../samples/smolagents-demo/README.md) | [smolagents](https://huggingface.co/docs/smolagents) | `@tool` → `SimpleTool.__call__` | `with sandboxes(...)` | 16 |
| [strands-agents-demo](../samples/strands-agents-demo/README.md) | [Strands Agents](https://strandsagents.com/) | `@tool` → `DecoratedFunctionTool.__call__` | `with sandboxes(...)` | 17 |

The conversation history is likewise each framework's own: an agent's session for Agno, the
`AssistantAgent`'s model context for AutoGen, the graph state for LangGraph,
`result.to_input_list()` for the OpenAI SDK, `message_history=` for Pydantic AI,
`reset=False` for smolagents, `agent.messages` for Strands, the session for ADK. CrewAI is the
exception worth noting: `kickoff()` is one-shot by design, so it needs an explicit mechanism
where a chat-native framework needs none.

## What every sample's test suite proves

`tests/test_tools_sandbox.py` is the same suite everywhere:

1. **Negative control**, in its own process, without the sandbox: the escape *succeeds*. A
   blocking assertion is worthless without it.
2. An **allowed host** is reached.
3. A **host outside the rules** is refused, and the refusal is read through
   `sandbox_denials()` — not by matching an error message.
4. The expression tool **still computes**.
5. The **escape is confined**: reaching `Popen` needs `process-exec`, which no profile grants.
6. The wrapper **names the rule** to the model.
7. A **whitelist guard**, run over *both* profiles: no `python-import=*`, no
   `python-api=ALLOW:process-exec`, no leftover `learn=` rule — a profile named but absent
   puts the run in learning mode, where the guards record instead of denying.
8. The **complete mode** confines the same calls, under `python-sb`.
