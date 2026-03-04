SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration_tests docker_tests help extended_tests

# Swith to poetry to uv
UV=uv
UV_EXTRA?=

# Default target executed when no arguments are given to make.
all: help

# Define a variable for the test file path.
TEST_FILE ?= tests

## Test the code
test:
	$(UV) run pytest -v $(TEST_FILE)

######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/experimental --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	$(UV) run mypy $(PYTHON_FILES)
	$(UV) run black $(PYTHON_FILES) --check
	$(UV) run ruff .

format format_diff:
	$(UV) run black $(PYTHON_FILES)
	$(UV) run ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	$(UV) run codespell --toml pyproject.toml

spell_fix:
	$(UV) run codespell --toml pyproject.toml -w


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
	$(UV) build

# ---------------------------------------------------------------------------------------
# SNIPPET pour publier la version sur pypi.org.
.PHONY: release
uv.lock: pyproject.toml
	uv lock
	git add poetry.lock
	uv sync $(UV_GROUP)


## Refresh lock
lock: $(LOCK)

## Validate the code
validate: $(UV).lock format lint spell_check test


_uv-init:
	@uv sync $(UV_GROUP)

## Start MCP inspector
inspector:
	npx @modelcontextprotocol/inspector

init: _$(UV)-init
