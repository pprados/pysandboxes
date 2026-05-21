SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration_tests docker_tests help extended_tests

UV=uv
UV_GROUP?=--group dev --group test

# Default target executed when no arguments are given to make.
all: help

# Define a variable for the test file path.
TEST_FILE ?= tests

## Test the code
tests:
	uv run python -m pytest -v $(TEST_FILE)

######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/experimental --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	uvx mypy $(PYTHON_FILES)
	uvx black $(PYTHON_FILES) --check
	uvx ruff check .

format format_diff:
	uvx black $(PYTHON_FILES)
	uvx ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	uvx codespell --toml pyproject.toml

spell_fix:
	uvx codespell --toml pyproject.toml -w


######################
# DOCUMENTATION
######################

## Clean the environment
clean:
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} \; || true
	@rm -Rf dist/ .mypy_cache .pytest_cache .ruff_cache

######################
# HELP
######################

.DEFAULT: help
## Print all majors target
help:
	@echo "$(bold)Available rules:$(normal)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=20 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) = Darwin && echo '--no-init --raw-control-chars')

	@echo -e "Use '$(cyan)make -B ...$(normal)' to force the target"
	@echo -e "Use '$(cyan)make -n ...$(normal)' to simulate the build"



.PHONY: dist
dist:
	uv build

# ---------------------------------------------------------------------------------------
# SNIPPET pour publier la version sur pypi.org.
.PHONY: release
uv.lock: pyproject.toml
	uv lock
	git add uv.lock
	uv sync $(UV_GROUP)


## Refresh lock
lock: uv.lock

## Validate the code
validate: uv.lock format lint spell_check tests


_uv-init:
	@uv sync $(UV_GROUP)

## Start MCP inspector
inspector:
	npx @modelcontextprotocol/inspector

init: _uv-init
