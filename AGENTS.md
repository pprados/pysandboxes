## Pattern Overview

**Overall:** Layered, multi-provider sandbox framework with defense-in-depth security model.

**Key Characteristics:**
- Python-level sandboxing layer (guards) + OS-level isolation layer (providers)
- Configuration-driven rule system with pluggable daemon providers
- Lazy loading and proxy patterns for circular import avoidance
- Learning mode for automatic rule generation from observed behavior
- Async/sync unified API supporting both decorator and context manager patterns

## Main
- Use uv to manage dependencies
- Unit Test: `make unit-tests`
- Integration Test: `make integration-tests`
- More info : `make help`

## Agents
To run the agents:
```bash
cd agents
uv venv
source .venv/bin/activate
make install
make run
```

## Samples
Each sample uses a dedicated directory and uv environment.
You must navigate to it before running the sample's tests.

```bash
cd samples/mcp-client
deactivate
# Activate the specific environment
source .venv/bin/activate
make help
make tests
```
The same applies to other samples.
