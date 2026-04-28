# Samples Clarification: Sandbox Protection for LLM Tools

## Problem Statement

Samples must clearly demonstrate pysandboxes protection for LLM tool invocation. Currently:
- Some samples have web-fetching tools without sandbox annotation
- No consistent test structure verifying network protection
- Unclear how to integrate `@sandbox` with framework tools

## Solution: Two-Scenario Testing

### Scenario A — Without Sandbox (Baseline)

**Context:** Tool called normally, pysandboxes not active.

**Tests:**
- Tool works as expected
- Returns content/success for any accessible URL
- No network restrictions

**Example:**
```python
def test_fetch_without_sandbox():
    result = fetch_webpage("https://example.com")
    assert len(result) > 0
```

### Scenario B — With Sandbox (Enforcement)

**Context:** Tool called via `@sandbox` decorator, `.py-sandboxes` config enforces rules.

**Tests (two sub-cases):**

**B1 — Blocked URL (not in config)**
```python
def test_fetch_sandbox_blocked():
    # URL not in .py-sandboxes net=ALLOW rules
    result = fetch_webpage("https://blocked.example.local")
    assert "Error" in result  # or exception raised
```

**B2 — Allowed URL (in config)**
```python
def test_fetch_sandbox_allowed():
    # URL listed in .py-sandboxes net=ALLOW rules
    result = fetch_webpage("https://example.com")
    assert len(result) > 0  # succeeds
```

## Implementation Pattern

### 1. Tool Definition (any framework)

```python
from pysandboxes import sandbox

@sandbox
def _fetch_webpage(url: str) -> str:
    """Inner function: sandboxed execution."""
    try:
        response = httpx.get(url, timeout=15)
        return response.text[:8000]
    except Exception as e:
        return f"Error: {e}"

def fetch_webpage(url: str) -> str:
    """Outer function: exposed to framework."""
    return _fetch_webpage(url)
```

**Why this pattern:**
- `@sandbox` runs inner function in restricted environment
- Outer wrapper adapts to framework's tool signature (async, tool decorators, etc)
- Error handling: `@sandbox` raises exceptions; wrapper converts to safe returns

### 2. Config: `.py-sandboxes`

```
py-sandbox=true
os-sandbox=subprocess
env=HOME=${HOME}

python-import=*
net=ALLOW|TCP|example.com|443|OUT
net=ALLOW|TCP|example.com|80|OUT
ro-bind=.,.
```

**Rules:**
- `py-sandbox=true`: Enable Python sandboxing
- `python-import=*`: Allow all Python module imports (sandbox controls at runtime)
- `net=ALLOW|TCP|HOST|PORT|OUT`: Explicitly allow outbound TCP to HOST:PORT
- Default: DENY all network access not listed

### 3. Tests: `tests/test_tools_sandbox.py`

**Structure:**
```python
# Scenario A: without sandbox
def test_fetch_without_sandbox():
    # No pysandbox setup
    result = fetch_webpage("https://example.com")
    assert ...

# Scenario B: with sandbox (marked as requiring runtime)
@pytest.mark.skipif(not os.environ.get("RUN_SANDBOX_TESTS"), ...)
def test_fetch_sandbox_blocked():
    # Runs inside pysandboxes runtime
    result = fetch_webpage("https://blocked.example.local")
    assert ...

def test_fetch_sandbox_allowed():
    # Runs inside pysandboxes runtime
    result = fetch_webpage("https://example.com")
    assert ...
```

## Files Created

### 1. `samples/conftest.py`

Shared pytest fixtures:
- `pysandbox_enabled()`: Context manager to activate sandbox for test scope
- `sandbox_config_allow_example()`: Fixture providing config allowing example.com
- `sandbox_config_deny_all()`: Fixture providing restrictive config

### 2. `samples/SANDBOX_INTEGRATION.md`

Detailed guide for adding sandbox to a sample:
- Tool pattern with `@sandbox` and wrapper
- Config structure
- Test structure (Scenario A & B)
- Checklist

### 3. `samples/README_SANDBOX_TESTS.md`

Overview of sandbox testing approach:
- Directory structure
- Running tests (baseline vs sandbox)
- Troubleshooting

### 4. `samples/mcp-server/tests/test_fetch_sandbox.py`

Example tests for MCP server sample:
- Scenario A: without sandbox (mocked network)
- Scenario B: with sandbox (integration tests)

## Integration Checklist

For each sample (pydantic-ai-demo, langgraph-demo, crewai-demo, etc):

- [ ] Add `.py-sandboxes` config to sample root
  - Allow relevant URLs (example.com for testing)
  - Import dependencies needed by tools
  - Allow read-bind of sample directory

- [ ] Wrap `fetch_webpage` with `@sandbox`:
  ```python
  @sandbox
  def _fetch_webpage(url: str) -> str: ...
  
  def fetch_webpage(url: str) -> str:
      return _fetch_webpage(url)
  ```

- [ ] Create `tests/test_tools_sandbox.py`:
  - Test Scenario A (without sandbox): fetch works
  - Test Scenario B (with sandbox):
    - Blocked URLs fail
    - Allowed URLs succeed

- [ ] Update sample README:
  - Document web tools' sandbox protection
  - Show how to test: `pytest tests/test_tools_sandbox.py`

## Running Tests

### Unit tests (Scenario A: without sandbox)
```bash
make unit-tests
```

### Container tests (Scenario B: with sandbox)
```bash
make container-tests
# Or per-sample:
cd samples/mcp-server
make tests  # if sample has Makefile
```

### Specific test
```bash
cd samples/pydantic-ai-demo
pytest tests/test_tools_sandbox.py::test_fetch_without_sandbox -v
pytest tests/test_tools_sandbox.py::test_fetch_sandbox_blocked -v
```

## Framework-Specific Notes

### Pydantic AI
- Tool function signature: `def fetch_webpage(url: str) -> str`
- No decorator needed; registered in `agent_factory.py`
- Async: Not required for this tool

### LangGraph
- Use `@tool` decorator on wrapper function
- Async OK with `async def fetch_webpage(...)`
- Inner `_fetch_webpage` handles sandboxing

### MCP Server (FastMCP)
- Tool registered via `@mcp.tool()` on wrapper
- Inner function with `@sandbox` handles execution
- Can be async

### CrewAI
- Tool in crew definition
- Wrapper function exposed
- Inner `@sandbox` function handles sandboxing

## Future: Other Samples

This clarification applies to all samples in `samples/`:
- agno-demo
- autogen-demo
- crewai-demo
- google-adk-demo
- langchain-demo
- langgraph-demo
- openai-agents-sdk-demo
- pydantic-ai-demo
- smolagents-demo
- strands-agents-demo

Each should follow the same pattern: `@sandbox` inner + framework wrapper.

## References

- **Pysandboxes docs**: `README.md` → `.py-sandboxes` config format
- **Example config**: `samples/mcp-server/.py-sandboxes`
- **Test pattern**: `samples/mcp-server/tests/test_fetch_sandbox.py`
