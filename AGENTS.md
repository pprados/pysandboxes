# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PySandboxes is a Python security framework that provides sandbox environments for executing untrusted Python code safely. The project uses a multi-layered defense-in-depth security architecture combining Python API patching with OS-level containers.

## Development Commands

### Testing
```bash
make test                    # Run unit tests
make integration_tests       # Run integration tests
make all-tests               # Run integration and unit tests
make gh-test                 # Run test in a simulation of github action
```

### Code Quality
```bash
make lint                    # Run all linters (mypy, black, ruff)
make format                  # Format code with black
make spell_check             # Check spell
make validate                # All validation
```

### Build and Distribution
```bash
make clean                   # Clean build artifacts
make dist                    # Build distribution packages
make publish-minor           # Increment and publish a minor version
make publish-patch           # Increment and publish a patch version
```

## Architecture

### Core Components
- **pysandboxes/sandboxes_api.py**: Main API with `@sandbox` decorator and `sandboxes()` context manager
- **pysandboxes/py_sandbox.py**: Python-level sandbox implementation using dynamic patching
- **pysandboxes/os_sandbox.py**: OS-level sandbox wrapper (firejail, Docker, etc.)
- **pysandboxes/guard_*.py**: Security guards for files, network, imports, and environment
- **pysandboxes/remote/**: Server-Sent Events (SSE) based IPC for remote execution

### Security Model
- **Default deny-all** with explicit whitelisting via `.py-sandboxes` configuration files
- **Multi-layered protection**: Python API patching + OS containers
- **Process isolation**: Main application communicates with sandboxed child processes via SSE over local HTTP
- **Learning mode**: Automatic security rule generation based on application behavior

### Configuration
Security rules are defined in `.py-sandboxes` files using a whitelist-based system:
- Located in working directory or as package resources
- Support for environment variable substitution
- Include mechanism for configuration composition
- Learning mode for automatic rule discovery

## Key Design Patterns

- **Decorator Pattern**: Use `@sandbox` to mark functions for sandbox execution
- **Context Manager**: Use `with sandboxes():` or `async with sandboxes():` for lifecycle management
- **Dynamic Patching**: Runtime modification of Python standard library functions
- **Whitelist Security**: Everything forbidden by default, explicit permissions required

## Development Environment

- **Python**: 3.11+ (tested up to 3.13)
- **Package Manager**: uv (exclusively — no poetry)
- **Virtual Environment**: `.venv/` directory
- **Entry Points**: `python-sb` CLI commands for sandboxed Python execution

## Code Quality
- Type hints required for all code
- Public APIs must have docstrings
- Functions must be focused and small
- Follow existing patterns exactly
- Line length: 78 chars maximum
- Always uses 3.10 syntax (str | None in place of Optional[str])
- avoid useless comments when generating code
- For all new file, add the comment:
```python
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
```

## Testing Strategy

- **Unit Tests**: `tests/unit_tests/` - Test individual components and guards
- **Integration Tests**: `tests/integration_tests/` - Test remote execution and full workflows
- **Async Support**: pytest-asyncio for testing async functionality

## Important Notes

- The project targets AI/LLM-generated code security use cases
- Configuration files use whitelist-only security model
- Multiple OS sandbox backends supported (firejail primary, Docker/podman planned)

## Code Security Verification

All generated code MUST be scanned with semgrep before committing:

```bash
# Scan with P/R rules (CRITICAL, HIGH, MEDIUM)
semgrep --config=p/security-audit pysandboxes/

# Scan generated file specifically
semgrep --config=p/security-audit <file>
```

### Semgrep Rules (Baseline)
Generated code verified against:
- **sql-injection**: SQL string concatenation, format strings in queries
- **command-injection**: Shell execution without proper escaping
- **hardcoded-secrets**: API keys, passwords, tokens in code
- **unsafe-deserialization**: pickle, yaml.load, json.loads on untrusted input
- **unsafe-file-operations**: Path traversal, symlink attacks
- **unsafe-regex**: ReDoS patterns in regular expressions
- **insecure-random**: random module vs secrets module
- **unvalidated-user-input**: Missing input validation at boundaries

### When Generating Code
1. Write code
2. Run semgrep scan
3. Fix findings before commit
4. If auto-fixes available: `semgrep --fix` applies them

### Disabling Rule (With Justification)
```python
# nosemgrep: <rule-id> — reason: <justification>
unsafe_code_here()
```
