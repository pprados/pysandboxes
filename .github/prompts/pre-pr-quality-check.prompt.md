---
description: 'Run the same checks locally that CI runs before opening or updating a pull request. This reduces CI failures and keeps feedback fast.'
agent: 'agent'
---

Run the same checks locally that CI runs before opening or updating a pull request. This reduces CI failures and keeps feedback fast.

## When to Use

- Before creating or updating a pull request
- After completing a feature to confirm CI will pass
- When CI fails and you want to reproduce and fix issues locally

## Context Validation Checkpoints

* [ ] Are dependencies installed? (uv sync with the right groups)
* [ ] Is the repo root the current directory? (Makefile targets assume project root)

## Command Steps

### Step 1: Format and lint

Format code and run lint (mypy, pyright, black, ruff). This matches the lint workflow.

make format
make lint

### Step 2: Run unit tests

Execute the unit test suite. This is the main test surface that CI runs.

make unit-tests

### Step 3: Run integration tests

Run integration tests if your change touches remote or sandbox behavior.

make integration-tests

### Step 4: (Optional) Run full test suite

To fully mirror CI (including container and sample tests), use make all-tests. Note: all-tests includes container-tests and sample-tests, which may require Docker/minikube and per-sample environments. For most PRs, format, lint, unit-tests, and integration-tests are sufficient.

make all-tests

### Step 5: (Optional) Run CI locally with act

If gh and act are installed, you can run the same GitHub Actions workflows locally.

make gh-tests
