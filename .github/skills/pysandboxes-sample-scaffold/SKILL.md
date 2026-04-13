---
name: 'pysandboxes-sample-scaffold'
description: 'This skill should be used when creating a new sample (sous-repertoire) under samples/ in the pysandboxes repository, with the same structure as mcp-client-demo and mcp-server-demo (Makefile, uv, README, AGENTS.md, tests, optional doc/config).'
---

# Pysandboxes Sample Scaffold

## Overview

To add a new sample to the pysandboxes repo, create a dedicated subdirectory under `samples/` with a consistent layout: **Makefile** and **uv** for build/test/lint, **README.md**, **AGENTS.md**, **.gitignore**, **pyproject.toml**, a Python package directory, and **tests/**.

## When to use this skill

- The user asks to create a new sample, example, or demo under `samples/`.
- The user wants a new subproject with the same structure as `samples/mcp-client-demo` or `samples/mcp-server-demo`.
- The user wants a Makefile + uv + README + doc layout for a new sample in this repo.

## Workflow

1. **Choose name and location**  
   - Sample directory: `samples/<name>/` with `<name>` in kebab-case (e.g. `my-demo`).  
   - Package directory: one folder in snake_case (e.g. `my_demo`) containing the Python code.

2. **Use the reference and templates**  
   - Read `references/sample-structure.md` for the full list of files, Makefile targets, pyproject layout, and conventions.  
   - Use the files in `assets/` as templates: copy them into the new sample root and rename (e.g. `Makefile.tpl` → `Makefile`, `gitignore.tpl` → `.gitignore`).  
   - Replace placeholders in templates:
     - `Makefile.tpl` → `Makefile` (no placeholders; use as-is).  
     - `pyproject.toml.tpl` → `pyproject.toml`: set `{{PROJECT_NAME}}`, `{{DESCRIPTION}}`, `{{AUTHOR}}`, `{{KEYWORDS}}`, `{{PACKAGE_DIR}}`.  
     - `README.md.tpl` → `README.md`: set `{{SAMPLE_TITLE}}`, `{{DESCRIPTION}}`, `{{SAMPLE_DIR}}`.  
     - `AGENTS.md.tpl` → `AGENTS.md` (use as-is or align with repo AGENTS.md Packmind block).  
     - `gitignore.tpl` → `.gitignore` (use as-is).

3. **Create package and tests**  
   - Create the package directory `samples/<name>/<package_dir>/` with `__init__.py` and application modules.  
   - Create `samples/<name>/tests/` with `__init__.py` and `test_*.py` as needed.

4. **Wire pyproject.toml**  
   - In `[tool.uv.sources]` keep `pysandboxes = { path = "../..", editable = true }` so the sample is built inside the pysandboxes repo.  
   - Set `[tool.hatch.build.targets.wheel]` `packages = ["<package_dir>"]` to the same name as the package directory.

5. **Document and validate**  
   - Complete README with installation (`uv sync`), usage, and how to run tests (`make tests`, `make validate`).  
   - Run from the sample directory: `uv sync`, `make help`, `make tests`, and optionally `make validate`.

## Resources

- **references/sample-structure.md**  
  Single reference for the required files (Makefile, pyproject.toml, README, AGENTS.md, .gitignore), directory layout, Makefile targets, and conventions. Load this when creating or auditing a sample.

- **assets/**  
  - `Makefile.tpl` → copy to `Makefile`.  
  - `pyproject.toml.tpl` → copy to `pyproject.toml` and replace `{{PROJECT_NAME}}`, `{{DESCRIPTION}}`, `{{AUTHOR}}`, `{{KEYWORDS}}`, `{{PACKAGE_DIR}}`.  
  - `README.md.tpl` → copy to `README.md` and replace `{{SAMPLE_TITLE}}`, `{{DESCRIPTION}}`, `{{SAMPLE_DIR}}`.  
  - `AGENTS.md.tpl` → copy to `AGENTS.md`.  
  - `gitignore.tpl` → copy to `.gitignore`.

## Conventions to respect

- One sample = one subdirectory under `samples/`, with its own `uv` environment (`.venv` in that directory).  
- Do not change `.pysandboxes` configuration (per project rules).  
- Keep the same Makefile targets and pyproject structure as in existing samples so `make help`, `make tests`, and `make validate` behave consistently.