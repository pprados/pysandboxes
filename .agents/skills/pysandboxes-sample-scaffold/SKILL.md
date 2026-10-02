---
name: pysandboxes-sample-scaffold
description: Use when creating a new sample under samples/ in the pysandboxes repository, with the same layout as the framework demos (agno-demo, langchain-demo, ...): Makefile, uv, pyproject.toml, README, tests, learn.py and .py-sandboxes profiles.
---

# Pysandboxes Sample Scaffold

## Overview

A sample is a self-contained subproject under `samples/<name>-demo/` with its own uv environment: **Makefile**, **pyproject.toml**, **README.md**, **.gitignore**, **env.example**, **learn.py**, the **.py-sandboxes** / **.py-sandboxes-complete** profiles, a Python package directory and **tests/**. The framework demos (`samples/agno-demo`, `samples/langchain-demo`, ...) are the reference; `mcp-client-demo`, `mcp-server-demo` and `quick-demo` are special cases.

## When to use this skill

- The user asks to create a new sample, example, or demo under `samples/`.
- The user wants a new subproject with the same structure as the existing framework demos.
- The user wants to audit an existing sample against the common layout.

## Workflow

1. **Choose name and location**
   - Sample directory: `samples/<name>-demo/`, kebab-case. The `-demo` suffix is required: the root Makefile builds the path as `samples/$(s)-demo`.
   - Package directory: snake_case (e.g. `my_demo`).

2. **Copy the templates** from `assets/` and replace the placeholders (`references/sample-structure.md` details each file):
   - `Makefile.tpl` → `Makefile`: `{{SAMPLE_NAME}}`, `{{PACKAGE_DIR}}`.
   - `pyproject.toml.tpl` → `pyproject.toml`: `{{SAMPLE_NAME}}`, `{{DESCRIPTION}}`, `{{AUTHOR}}`, `{{KEYWORDS}}`, `{{PACKAGE_DIR}}`.
   - `README.md.tpl` → `README.md`: `{{SAMPLE_TITLE}}`, `{{DESCRIPTION}}`, `{{SAMPLE_DIR}}`.
   - `gitignore.tpl` → `.gitignore` (as-is).
   - `AGENTS.md.tpl` → `AGENTS.md`: optional, only if the sample needs agent rules of its own.

3. **Write the code and tests**
   - `<package_dir>/__init__.py` and `<package_dir>/main.py` exposing `main()` (target of `[project.scripts]`, used by `make run`).
   - `tests/conftest.py` and `tests/test_*.py`.

4. **Add the sandbox files**, adapted from the closest existing sample (they are framework-specific, there is no template):
   - `env.example`: the variables the sample reads, without values.
   - `learn.py`: the script exercised by `make learn`.
   - `.py-sandboxes` and `.py-sandboxes-complete`: generate them with `make learn`, then review them. Learning only adds rules and never produces `net=` rules.

5. **Register the sample** in the root `Makefile`: add `<name>` (without `-demo`) to `SAMPLES`. This enables `sample-tests-<name>` and `pip-audit` for it, and therefore CI.

6. **Validate** from the sample directory: `make init`, `make help`, `make validate`. Then, from the repo root, `make sample-tests-<name>`.

## Resources

- `references/sample-structure.md`: required files, Makefile targets, pyproject layout, conventions. Load it when creating or auditing a sample.
- `assets/`: the templates listed above.

## Conventions to respect

- One sample = one directory under `samples/` with its own `.venv`. Never use the root venv.
- Do not modify the root `.pysandboxes` configuration.
- Keep the Makefile targets and pyproject layout identical to the other samples, so `make help`, `make tests` and `make validate` behave the same everywhere.
