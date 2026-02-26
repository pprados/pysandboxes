# Integrating with the MCP SDK

Anthropic offers a standard [MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

This presents a valuable opportunity to use **Py-sandboxes**. The tools and APIs exposed by an MCP server can be abused by manipulating the LLM's responses.

For example:
- A tool for fetching a web page could be manipulated to access internal intranet pages or `localhost` (To access API details, or to enter a recursive loop of page requests).
- An LLM that generates Python code and then invokes a tool to execute it could go beyond the developer's intended scope.

In these scenarios, **Pysandboxes** provides a solution.

## Usage with `python-sb` (complete mode)

In this scenario, the entire MCP server is encapsulated within the sandbox. Simply launch it using `python-sb` instead of `python`.

On the first run, if you want to associate a specific configuration file, use the `--learn` parameter as follows:

```
python-sb --learn=demo_mcp/.pysandboxes -m demo_mcp.calc sse
```

After using the server to exercise all its *normal* functionalities, interrupt the process (*Ctrl-C* or `kill -2 <pid>`) to generate the rules learned during its operation.

From then on, you can launch the MCP server without the `--learn` parameter to enforce the generated security profile.

## Usage by Selecting Functions to Protect (partial mode)

To isolate a tool in the sandbox, start to launch the sandbox

```python
with sandboxes(
    config_path="demo_mcp/.py-sandboxes",
):
    mcp.run(transport=transport)
```
and simply add the `@sandbox` decorator.
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

The MCP SDK framework allows a tool to access the MCP server itself by adding a `ctx: Context` parameter. Since the context object exists outside the sandbox, it cannot be serialized and sent to the protected version of the code.

To solve this, split the function in two: one part that handles the context in the main process and another, sandboxed part that performs the evaluation.

```python
@mcp.tool(name="evaluate_expression",
          description="Evaluates a mathematical expression and returns the result")
async def evaluate_expression(expression: str, ctx: Context) -> float:
    # This function runs in the main process and has access to the context.
    # It calls the sandboxed helper function to perform the actual work.
    return await _evaluate_expression(expression)

@sandbox
async def _evaluate_expression(expression: str) -> float:
    # This function is sandboxed and does not have access to the context.
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
and use it. It's secure.
