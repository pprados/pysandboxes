# Sandbox Tests for Samples

This directory contains samples demonstrating pysandboxes protection for LLM tool invocation.

## Structure

```
samples/
├── conftest.py                      # Shared pytest fixtures
├── SANDBOX_INTEGRATION.md           # How to add sandbox to samples
├── README_SANDBOX_TESTS.md          # This file
├── mcp-server/
│   ├── mcp_server/main.py          # MCP server with @sandbox tools
│   ├── tests/
│   │   ├── test_fetch_sandbox.py   # Sandbox tests for fetch_webpage
│   │   └── ...
│   └── .py-sandboxes               # Sandbox config
├── mcp-client/
│   └── ...
└── [Other samples]
    ├── tools.py                     # @sandbox decorated functions
    ├── tests/
    │   ├── test_tools_sandbox.py   # Sandbox tests
    │   └── ...
    └── .py-sandboxes               # Sandbox config
```

## Two Test Scenarios

### Scenario A: Without Sandbox (Baseline)

**What:** Tool called normally, no sandbox active.

**Tests:**
- `test_fetch_without_sandbox_returns_content()`: fetch succeeds
- `test_fetch_without_sandbox_returns_error_on_exception()`: handles errors

**Run:**
```bash
cd samples/mcp-server
pytest tests/test_fetch_sandbox.py -k "without_sandbox"
```

### Scenario B: With Sandbox (Enforcement)

**What:** Tool called via pysandboxes runtime, network rules enforced.

**Tests:**
- `test_fetch_webpage_sandbox_blocks_unauthorized()`: blocked URLs
- `test_fetch_webpage_sandbox_allows_configured()`: allowed URLs

**Run (requires sandbox runtime):**
```bash
cd samples/mcp-server
RUN_SANDBOX_TESTS=1 pytest tests/test_fetch_sandbox.py -k "sandbox"

# Or with full container:
make container-tests
```

## Adding to a New Sample

1. **Create `.py-sandboxes` config:**
   ```
   py-sandbox=true
   os-sandbox=subprocess
   env=HOME=${HOME}
   python-import=*
   net=ALLOW|TCP|example.com|443|OUT
   net=ALLOW|TCP|example.com|80|OUT
   expose-ro=.
   ```

2. **Add `@sandbox` decorator to tools:**
   ```python
   from pysandboxes import sandbox
   
   @sandbox
   def _fetch_webpage(url: str) -> str:
       # implementation
   ```

3. **Create test file** `tests/test_tools_sandbox.py`:
   ```python
   from samples.conftest import pysandbox_enabled
   
   def test_fetch_without_sandbox():
       result = fetch_webpage("https://example.com")
       assert len(result) > 0
   
   @pytest.mark.skipif(not os.environ.get("RUN_SANDBOX_TESTS"), ...)
   def test_fetch_with_sandbox():
       # Run inside pysandboxes runtime
       result = fetch_webpage("https://example.com")
       assert len(result) > 0
   ```

## Running All Tests

```bash
# Unit tests (no sandbox)
make unit-tests

# Container tests (with sandbox)
make container-tests

# Specific sample
cd samples/pydantic-ai-demo
pytest tests/test_tools_sandbox.py
```

## Key Points

- **@sandbox decorator:** Marks function as sandbox-protected
- **.py-sandboxes config:** Defines network rules, file access, imports
- **Error handling:** @sandbox raises exceptions; wrappers convert to safe returns
- **Deterministic:** Tests use mocks to avoid real network calls
- **Two modes:** Without sandbox (baseline) and with (enforcement)

## Troubleshooting

**Test fails in "with sandbox" mode:**
- Check `.py-sandboxes` config allows the URL
- Verify `python-import=*` includes dependencies (httpx, etc)
- Run with `RUN_SANDBOX_TESTS=1` explicitly

**Import errors in sandbox:**
- Add module to `python-import=` in `.py-sandboxes`
- Check it's not in the "dangerous" blocklist

**Network timeouts:**
- `.py-sandboxes` may be too restrictive
- Test with `net=ALLOW|TCP|0.0.0.0/0|80|OUT` temporarily for debugging
