SHELL=/bin/bash
.PHONY: all format lint run learn test tests help clean init lock validate

UV_GROUP?=--group dev --group test

all: help

TEST_FILE ?= tests

## Run pytest (uses project venv via uv — do not run bare `pytest` on PATH)
tests:
	set -a && if [ -f .env ]; then source .env; fi && uv run $(UV_GROUP) pytest -v $(TEST_FILE)

test: tests

## Start the interactive chat (Ctrl-D or /quit to leave)
run:
	set -a && if [ -f .env ]; then source .env; fi && uv run {{SAMPLE_NAME}}

## Relearn both profiles, one per mode. Read learn.py first: learning only ever
## adds, it must never run on untrusted code, and every `net=` rule it writes needs review.
learn:
	uv run python learn.py
	uv run python -m pysandboxes.python_sb \
		--pysandboxes-config=.py-sandboxes-complete \
		--learn=.py-sandboxes-complete learn.py

lint format: PYTHON_FILES={{PACKAGE_DIR}} tests
lint:
	uvx mypy $(PYTHON_FILES)
	uvx black $(PYTHON_FILES) --check
	uvx ruff check $(PYTHON_FILES)

format:
	uvx black $(PYTHON_FILES)
	uvx ruff check --select I --fix $(PYTHON_FILES)

## Clean caches
clean:
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} \; || true
	@rm -Rf dist/ .mypy_cache .pytest_cache .ruff_cache

.DEFAULT: help
## Print all major targets
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

## Refresh uv.lock
lock:
	uv lock

## Validate (lint, tests)
validate: lint tests

_uv-init:
	@uv sync $(UV_GROUP)

## Install deps with uv
init: _uv-init
