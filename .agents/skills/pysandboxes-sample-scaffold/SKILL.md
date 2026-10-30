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
- The user wants to audit an existing sample against the common layout (see "Auditing a sample").

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
   - Every new `.py` file starts with `# Copyright (c) 2026, Philippe PRADOS` and `# License: Apache V2`. Type hints everywhere, Python 3.11 syntax (`str | None`), lines of at most 120 characters, no useless comments. A test must be able to fail: never set `OS_SANDBOX=none`, give each blocking assertion a negative control, and make sure every profile a test names exists on disk (a missing profile silently switches to learning mode, where nothing is denied).

4. **Add the sandbox files**, adapted from the closest existing sample (they are framework-specific, there is no template):
   - `env.example`: the variables the sample reads, without values.
   - `learn.py`: the script exercised by `make learn`.
   - `.py-sandboxes` and `.py-sandboxes-complete`: generate them with `make learn`, then review them. Learning only adds rules; review every `net=` rule it writes, since which hosts a tool may reach is the author's decision.

5. **Register the sample** in the root `Makefile`: add `<name>` (without `-demo`) to `SAMPLES`. This enables `sample-tests-<name>` and `pip-audit` for it, and therefore CI.

6. **Validate** from the sample directory: `make init`, `make help`, `make validate`. Then, from the repo root, `make sample-tests-<name>`. CI runs the samples on Python 3.11 to 3.14, and `make sample-tests-matrix` runs them on every Python and every OS provider (the maintainer's check before a minor or final release).

7. **Document and commit**
   - Add one user-facing line to the open `## [0.0.0] - 202X-XX-XX` entry of `CHANGELOG.md`, under `### Added` (never date it nor add a version).
   - Search the repository for the name of an existing sample (`rg -l <existing>-demo`) and add the new one wherever the samples are listed, such as `README.md` or the `wiki/`.
   - Commit `uv.lock` with the sample. Commit subjects follow Conventional Commits (`feat(samples): ...`). Branch from `develop`; the pull request targets `develop`.

## Auditing a sample

Compare the sample to `references/sample-structure.md` and to the closest existing sample, and report each gap without fixing it unasked:

- required files present (`Makefile`, `pyproject.toml`, `uv.lock`, `README.md`, `.gitignore`, `env.example`, `learn.py`, both `.py-sandboxes*` profiles);
- Makefile targets and pyproject layout identical to the other samples (`diff` against the reference sample);
- name in `SAMPLES` of the root `Makefile`;
- copyright header on every `.py` file;
- every `net=` rule of the profiles justified, and no `expose-rw` wider than needed;
- `make validate` green from the sample directory, then `make sample-tests-<name>` from the root.

## Resources

- `references/sample-structure.md`: required files, Makefile targets, pyproject layout, conventions. Load it when creating or auditing a sample.
- `assets/`: the templates listed above.

## Conventions to respect

- One sample = one directory under `samples/` with its own `.venv`. Never use the root venv.
- Do not modify the root `.py-sandboxes` configuration.
- Keep the Makefile targets and pyproject layout identical to the other samples, so `make help`, `make tests` and `make validate` behave the same everywhere.
