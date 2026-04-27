---
description: 'Each sample in this repo uses its own directory and uv environment. To run a sample''s tests, activate that environment and run its Make targets from the sample directory.'
agent: 'agent'
---

Each sample in this repo uses its own directory and uv environment. To run a sample's tests, activate that environment and run its Make targets from the sample directory.

## When to Use

- Verifying that a sample (e.g. mcp-client-demo, mcp-server-demo) still works after changes
- Debugging sample-specific behavior
- Before running make sample-tests or make all-tests from the repo root, to run one sample in isolation

## Context Validation Checkpoints

* [ ] Are you in the correct sample directory? (e.g. samples/mcp-client-demo)
* [ ] Is the sample's virtual environment created and activated? (uv venv and source .venv/bin/activate)

## Command Steps

### Step 1: Navigate to the sample directory

From the repository root, cd to the sample (e.g. samples/mcp-client-demo or samples/mcp-server-demo).

cd samples/mcp-client-demo

### Step 2: Ensure a virtual environment exists

If the sample has a Makefile that sets up the env, run make install. Otherwise create and sync with uv.

make install
# or: uv venv && source .venv/bin/activate && uv sync

### Step 3: Run the sample's tests

Use the sample's own test target or run pytest directly in that directory.

make tests
# or: pytest -v

### Step 4: Return to repo root (optional)

When done, cd back to root and deactivate. From the repo root, make sample-tests runs tests for configured samples in sequence.

cd ../..
deactivate
