# Integrating with the MCP SDK

The [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) exposes tools to an LLM. Prompt injection can
steer a web fetcher to internal hosts or make a code execution tool exceed its intended scope. PySandboxes limits
the server or selected tools.

## Usage with `python-sb` (complete mode)

Complete mode confines the whole server. Launch it with `python-sb` instead of `python`.

On the first run, generate rules in a chosen file with `--learn`:

```
python-sb --learn=demo_mcp/.py-sandboxes -m demo_mcp.calc sse
```

Exercise the server's normal functions, then stop it with Ctrl-C. Review the generated rules. Start it without
`--learn` to enforce them.

## Usage by Selecting Functions to Protect (partial mode)

Use partial mode to isolate selected tools. Start the sandbox:

```python
with sandboxes(
    sandboxes_config="demo_mcp/.py-sandboxes",
):
    mcp.run(transport=transport)
```
Add `@sandbox` to each tool implementation:
```python
@sandbox
@mcp.tool(name="evaluate_expression",
          description="Evaluates a mathematical expression and returns the result")
async def evaluate_expression(expression: str) -> float:
    """Evaluates a mathematical expression and returns the result."""
    try:
        # Warning: eval() is unsafe for untrusted input; use a proper parser in production
        result = eval(expression, {"__builtins__": {}},
                      {"add": add, "sub": sub, "mul": mul, "truediv": truediv})
        return result
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")
```

An MCP tool can receive `ctx: Context`. The context belongs to the main process and cannot be serialized into the
sandbox.

Split the tool into a main-process wrapper and a sandboxed helper. The wrapper uses the context; the helper does
the protected work.

```python
@mcp.tool(name="evaluate_expression",
          description="Evaluates a mathematical expression and returns the result")
async def evaluate_expression(expression: str, ctx: Context) -> float:
    # Runs in the main process and can use the context.
    return await _evaluate_expression(expression)

@sandbox
async def _evaluate_expression(expression: str) -> float:
    # Runs in the sandbox without the context.
    try:
        result = eval(expression, {"__builtins__": {}},
                      {"add": add, "sub": sub, "mul": mul, "truediv": truediv})
        return result
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")
```

# Sample use
To add the *Demo MCP Server* in Claude, use something like this:
```bash
claude mcp add --scope project demo -- python-sb -m demo_mcp.calc
```
and use it. The sandbox constrains supported operations according to its profile and selected OS provider; it is not a blanket guarantee for every tool or provider. Review the [security model](security-model.md), [known weaknesses](weaknesses.md), and [provider limits](os-providers.md) for the configuration you deploy.
