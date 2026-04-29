# autogen-demo

Console demo of [Microsoft AutoGen](https://github.com/microsoft/autogen) **AgentChat** with two tools—**HTTP fetch** and **restricted Python execution**—driven by the model’s tool calls (not hard-coded script logic).

The default task **requires** both tools: it asks the model to fetch `https://www.google.com`, parse the HTML in Python, and report a word count. **This is not an OS-level sandbox**; `execute_python` is a small `exec` demo only.

## Prerequisites

- Python 3.10+
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

```bash
# Uses CHAT_MODEL and provider keys from the environment
autogen-demo

# Custom task (must still require tool use)
autogen-demo --task "Fetch https://www.google.com ..."

# Verbose: stream AgentChat console output
autogen-demo -v

# Tool rounds (maps to AssistantAgent `max_tool_iterations`)
autogen-demo --max-tool-iterations 15
```

### Sandbox integration (python-sb)

Run `execute_python` inside an **OS-level container** instead of just a namespace-restricted `exec`:

```bash
# Requires python-sb installed
autogen-demo --use-python-sb

# Sandbox + custom task
autogen-demo --use-python-sb --task "Your custom task here"
```

**Setup python-sb:**
```bash
cd samples/autogen-demo
uv pip install python-sb
```

**Comparison:**
| Mode | Isolation | Speed | Setup |
|------|-----------|-------|-------|
| Default (`tools.py`) | Namespace + allowlist | Fast | None |
| `--use-python-sb` | OS container (qemu/unshare) | Slower | `uv pip install python-sb` |

### Annotated tools

Use tools with **JSON Schema metadata** for better model type awareness:

```bash
autogen-demo --annotated-tools
```

**What changes:**
- Each tool exposes `.parameters` (JSON Schema) for the model
- Model can introspect exact parameter types and requirements before calling
- Reduces  "wrong parameter shape" errors

**Layout:**
- `tools_annotated.py` — Same tools, wrapped with `ToolMetadata` + JSON Schema
- Model sees structured parameter hints, not just docstrings

## Tests

```bash
make tests
# or
make validate   # lint + tests (no network, no API keys)
```

## Layout

- `autogen_demo/tools.py` — Default tools: `fetch_webpage`, `execute_python` (namespace-restricted)
- `autogen_demo/tools_sandbox.py` — `execute_python` inside python-sb OS container (use with `--use-python-sb`)
- `autogen_demo/tools_annotated.py` — Same tools with JSON Schema metadata (use with `--annotated-tools`)
- `autogen_demo/model_client.py` — `CHAT_MODEL` → `ChatCompletionClient`
- `autogen_demo/run.py` — `AssistantAgent` + `run_stream` + tool routing
- `autogen_demo/main.py` — CLI with flags for sandbox/annotated modes

**Runtime dependencies:**
- Default: No external sandbox library
- `--use-python-sb`: Requires `python-sb` (in-tree at `python-sb/`)
