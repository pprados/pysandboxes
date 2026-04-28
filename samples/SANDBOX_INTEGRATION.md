# Sandbox Integration for Samples

Each sample must demonstrate pysandboxes protection for web tools.

## Structure

### 1. Tool: `fetch_webpage(url: str) -> str`

Each framework sample must expose a web-fetching tool:

```python
from pysandboxes import sandbox

@sandbox
def _fetch_webpage(url: str) -> str:
    """Fetch URL, return content or error."""
    try:
        response = httpx.get(url, timeout=15)
        response.raise_for_status()
        return response.text[:8000]
    except Exception as e:
        return f"Error: {e}"

def fetch_webpage(url: str) -> str:
    """Wrapper exposed to framework."""
    return _fetch_webpage(url)
```

**Key points:**
- Inner function decorated with `@sandbox` (sandboxes the execution)
- Wrapper exposes to framework (MCP, Pydantic AI, LangGraph, etc)
- Returns error string on failure (no exceptions leak)
- Truncates large responses

### 2. Tests: Two Scenarios

#### Scenario A — Without Sandbox (Baseline)

```python
def test_fetch_without_sandbox():
    """Works when sandbox not active."""
    result = fetch_webpage("https://example.com")
    assert len(result) > 0
    assert "Error" not in result
```

Run in normal environment. Sandbox disabled.

#### Scenario B — With Sandbox (Enforcement)

```python
def test_fetch_with_sandbox_blocked(sandbox_config_deny_all):
    """Blocked when sandbox active + URL not allowed."""
    with pysandbox_enabled():
        result = fetch_webpage("https://disallowed-site.example.local")
        assert "Error" in result
        # Or: connection refused, timeout, etc.

def test_fetch_with_sandbox_allowed(sandbox_config_allow_example):
    """Allowed when sandbox active + URL in config."""
    with pysandbox_enabled():
        result = fetch_webpage("https://example.com")
        assert len(result) > 0
        assert "Error" not in result
```

Run with `pysandbox_enabled()` context. Sandbox enforces network rules from `.py-sandboxes`.

### 3. Integration Point

Each sample framework invokes the tool:

- **Pydantic AI:** Tool registered in `agent_factory.py`
- **LangGraph:** Tool decorator on `@tool` function
- **MCP Server:** Tool registered via `@mcp.tool()`
- **CrewAI:** Tool in crew definition
- **etc.**

## Config: `.py-sandboxes`

Minimal config for testing:

```
py-sandbox=true
os-sandbox=subprocess
env=HOME=${HOME}

python-import=*
net=ALLOW|TCP|example.com|443|OUT
net=ALLOW|TCP|example.com|80|OUT

ro-bind=.,.
```

Allows outbound to `example.com`, denies all others.

## Checklist: Adding to a Sample

- [ ] Tool `fetch_webpage()` decorated with `@pysandbox`
- [ ] Tool returns error string, not exception
- [ ] Test: `test_fetch_without_sandbox()` (baseline)
- [ ] Test: `test_fetch_with_sandbox_blocked()` (deny)
- [ ] Test: `test_fetch_with_sandbox_allowed()` (allow)
- [ ] `.py-sandboxes` config in sample root
- [ ] Conftest imports fixtures from `samples/conftest.py`

## Example: Pydantic AI

**File:** `samples/pydantic-ai-demo/pydantic_ai_demo/tools.py`

```python
from pysandboxes import pysandbox

@pysandbox
def fetch_webpage(url: str) -> str:
    """HTTP GET URL, return text (truncated)."""
    try:
        response = httpx.get(url, timeout=15)
        response.raise_for_status()
        text = response.text
        return text[:8000] + ("... [truncated]" if len(text) > 8000 else "")
    except Exception as e:
        return f"Error fetching {url}: {type(e).__name__}: {e}"
```

**File:** `samples/pydantic-ai-demo/tests/test_tools_sandbox.py`

```python
from pathlib import Path
import pytest
from pydantic_ai_demo.tools import fetch_webpage
from samples.conftest import pysandbox_enabled

def test_fetch_without_sandbox():
    result = fetch_webpage("https://example.com")
    assert len(result) > 10
    assert "Error" not in result[:20]

def test_fetch_with_sandbox_blocked(sandbox_config_deny_all):
    with pysandbox_enabled():
        result = fetch_webpage("https://blocked.example.local")
        assert "Error" in result or len(result) < 10

def test_fetch_with_sandbox_allowed(sandbox_config_allow_example):
    with pysandbox_enabled():
        result = fetch_webpage("https://example.com")
        assert len(result) > 10
```

## Running Tests

```bash
# All samples
make tests

# Single sample
cd samples/pydantic-ai-demo
pytest tests/test_tools_sandbox.py
```
