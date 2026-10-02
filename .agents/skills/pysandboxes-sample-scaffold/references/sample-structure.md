# Structure of a pysandboxes sample

This document describes the layout shared by the framework samples (e.g. `samples/agno-demo`, `samples/langchain-demo`), to reproduce for any new sample.

## Location

- Each sample is a **subdirectory** of `samples/` at the repository root.
- Directory name: kebab-case ending in `-demo`, e.g. `agno-demo`, `my-new-demo`. The root Makefile derives the path as `samples/$(s)-demo`.

## Files at the sample root

| File | Required | Role |
|------|----------|------|
| `Makefile` | yes | Targets: `help`, `tests`, `test`, `run`, `learn`, `lint`, `format`, `validate`, `init`, `lock`, `clean`. Uses `uv` and `uvx`. |
| `pyproject.toml` | yes | `uv` project: dependency groups `dev`, `test`, `codespell`; editable `pysandboxes` source at `../..`. |
| `uv.lock` | yes | Committed lock file (`make lock`). |
| `README.md` | yes | Installation (`uv sync`), usage, sample documentation. |
| `.gitignore` | yes | See below. |
| `env.example` | yes | Environment variables read by the sample, without values. Copied to `.env` (ignored) by the user. |
| `learn.py` | yes | Script run by `make learn` to relearn the sandbox profiles. |
| `.py-sandboxes` | yes | Sandbox profile for the default mode. |
| `.py-sandboxes-complete` | yes | Sandbox profile for the complete mode. |
| `AGENTS.md` | no | Agent rules specific to the sample (e.g. Packmind standards block). |

## Makefile

- `SHELL=/bin/bash`, `.PHONY` for the main targets, default target `all: help`.
- `UV_GROUP?=--group dev --group test`, `TEST_FILE ?= tests`.
- **Tests**: `tests` runs `uv run pytest -v $(TEST_FILE)` after `set -a` and `source .env` when present; `test` is an alias.
- **Run**: `run` sources `.env` then runs `uv run <sample-name>` (the `[project.scripts]` entry).
- **Learn**: `learn` runs `learn.py` once per profile; the complete mode goes through `python -m pysandboxes.python_sb --pysandboxes-config=.py-sandboxes-complete --learn=.py-sandboxes-complete learn.py`.
- **Lint / format**: `PYTHON_FILES=<package_dir> tests`; `lint` runs `uvx mypy`, `uvx black --check`, `uvx ruff check`; `format` runs `uvx black` and `uvx ruff check --select I --fix`.
- **Clean**: removes `.ipynb_checkpoints`, `dist/`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`.
- **Help**: `help` lists the targets from their `##` comments (sed + awk).
- **Lock / init**: `lock` runs `uv lock`; `init: _uv-init` runs `uv sync $(UV_GROUP)`.
- **Validate**: `validate: lint tests`.

The `##` comment above a target is its description in `make help`.

## pyproject.toml

- `[project]`: `name`, `version`, `description`, `readme`, `requires-python = ">=3.11"`, `license`, `classifiers`, `dependencies` (starting with `pysandboxes`).
- `[dependency-groups]`: `dev` (ipython, pyright, ruff), `test` (pytest, pytest-asyncio, pytest-mock), `codespell`.
- `[project.scripts]`: `<sample-name> = "<package_dir>.main:main"`.
- `[tool.uv.sources]`: `pysandboxes = { path = "../..", editable = true }`.
- `[build-system]`: `hatchling`; `[tool.hatch.build.targets.wheel]` with `packages = ["<package_dir>"]`.
- Tools: `[tool.pyright]` (include package and tests, `.venv`), `[tool.black]` and `[tool.ruff]` (line-length 120, py310), `[tool.ruff.lint]` (`E`, `F`, `I`), `[tool.codespell]`, `[tool.pytest.ini_options]` (`--strict-markers --strict-config -vv`).

The Python package (directory) name is snake_case, e.g. `agno_demo`.

## README.md

- Title and short description.
- **Installation**: `cd samples/<sample>` then `uv sync` (or `make init`).
- **Usage**: `make run`, the variables of `env.example`, example commands.
- **Tests**: `make tests`, `make validate`.

## .gitignore

```
.local.py-sandboxes
.env
.venv
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
.benchmarks/

# Backups written by learning mode (see learn.py)
.py-sandboxes*.old*
```

## Directories

- **Python package**: snake_case directory with `__init__.py`, `main.py` (`main()`) and the sample modules.
- **tests/**: `conftest.py` and `test_*.py`.

## Registration in the repository

- Add `<name>` (without `-demo`) to `SAMPLES` in the root `Makefile`. This creates `sample-tests-<name>` and includes the sample in `sample-tests` and `pip-audit`, hence in CI.

## Conventions

- Each sample has its **own uv environment** (`.venv` in the sample directory). Never share the root venv.
- Run tests from the sample directory (`make tests`, `make validate`) or from the root (`make sample-tests-<name>`).

## User commands

```bash
cd samples/<name>-demo
make init
make help
make validate
cd ../..
make sample-tests-<name>
```
