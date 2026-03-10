SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration-tests docker_tests help extended_tests

# Swith to poetry to uv
UV_EXTRA?=
UV_GROUP?=--group dev --group lint --group test

POETRY_EXTRA?=
POETRY_WITH?=-with dev,lint,test,codespell

# Default target executed when no arguments are given to make.
all: help

.vscode/launch.json: .idea/runConfigurations/*
	claude -p "Update the .vscode/launch.json file with the modification of the files in .idea/runConfigurations/"

# Fix VS Code launch.json
fix-vs-code: .vscode/launch.json

## Make unit test
unit-tests:
	uv run pytest -v tests/unit_tests/

## Make integration tests
integration-tests:
	uv run pytest tests/integration_tests

## Make integration tests
sample-tests:
	(cd samples/mcp-client && make test)
	(cd samples/mcp-server && make test)

## Make github tests locally
gh-tests: lint
	gh act push

## Make all tests
all-tests: unit-tests integration-tests sample-tests

test_watch:
	uv run ptw --now . -- tests/unit_tests


######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
PYTHON_FILES=pysandboxes/ tests/
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/experimental --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint: format
	uv run mypy $(PYTHON_FILES)
	uv run black --check $(PYTHON_FILES)
	uv run ruff check $(PYTHON_FILES)

claude-lint: lint
	claude -p 'you are a linter. please look at the changes vs. main and report any issues related to typos. report the filename and line number on one line, and a description of the issue on the second line. do not return any other text.'

format format_diff:
	uv run black $(PYTHON_FILES)
	uv run ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	uv run codespell --toml pyproject.toml

spell_fix:
	uv run codespell --toml pyproject.toml -w


######################
# DOCUMENTATION
######################

# Clean the environment
clean: docs_clean api_docs_clean
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} \; || true
	@rm -Rf dist/ .make-* .mypy_cache .pytest_cache .ruff_cache

docs_build:
	docs/.local_build.sh

docs_clean:
	rm -rf docs/_dist

docs_linkcheck:
	poetry run linkchecker docs/_dist/docs_skeleton/ --ignore-url node_modules

api_docs_build:
#	poetry run python docs/api_reference/create_api_rst.py
#	cd docs/api_reference && poetry run make html

api_docs_clean:
#	rm -f docs/api_reference/api_reference.rst
#	cd docs/api_reference && poetry run make clean


api_docs_linkcheck:
	uv run linkchecker docs/api_reference/_build/html/index.html

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
# SNIPPET pour tester la publication d'une distribution
# sur test.pypi.org.
.PHONY: test-twine
## Publish distribution on test.pypi.org
test-twine: dist
ifeq ($(OFFLINE),True)
	@echo -e "$(red)Can not test-twine in offline mode$(normal)"
else
	@$(VALIDATE_VENV)
	rm -f dist/*.asc
	twine upload --sign --repository-url https://test.pypi.org/legacy/ \
		$(shell find dist -type f \( -name "*.whl" -or -name '*.gz' \) -and ! -iname "*dev*" )
endif

# ---------------------------------------------------------------------------------------
# SNIPPET pour publier la version sur pypi.org.
.PHONY: release
## Publish distribution on pypi.org
release: validate all-tests clean dist
ifeq ($(OFFLINE),True)
	@echo -e "$(red)Can not release in offline mode$(normal)"
else
	@$(VALIDATE_VENV)
	[[ $$( find dist -name "*.dev*" | wc -l ) == 0 ]] || \
		( echo -e "$(red)Add a tag version in GIT before release$(normal)" \
		; exit 1 )
	rm -f dist/*.asc
	echo "Enter Pypi password"
	twine upload  \
		$(shell find dist -type f \( -name "*.whl" -or -name '*.gz' \) -and ! -iname "*dev*" )

endif

poetry.lock: pyproject.toml
	poetry lock
	git add poetry.lock
	poetry install $(POETRY_EXTRA) -$(POETRY_WITH)

uv.lock: pyproject.toml
	uv lock
	git add poetry.lock
	uv sync $(UV_GROUP)


## Refresh lock
lock: $(LOCK)

## Validate the code
validate: uv.lock format lint spell_check test


_poetry-init:
	@poetry self update
	@poetry self add poetry-dotenv-plugin
	@poetry self add poetry-plugin-export
	@poetry self add poetry-git-version-plugin
	@poetry config virtualenvs.in-project true
	@poetry install --sync $(POETRY_EXTRA) --with $(POETRY_WITH)
	@pre-commit install

_uv-init:
	@uv sync $(UV_GROUP)

## Start MCP inspector
inspector:
	npx @modelcontextprotocol/inspector

github-push-test:
	gh act push

init: _uv-init
#	@pre-commit install
	gh extension install https://github.com/nektos/gh-act
	@git lfs install
