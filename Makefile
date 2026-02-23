SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration_tests docker_tests help extended_tests

# Swith to poetry to uv
POETRY_OR_UV=uv
LOCK=$(POETRY_OR_UV).lock
UV_EXTRA?=
UV_GROUP?=--group dev --group lint --group test --group codespell

POETRY_EXTRA?=
POETRY_WITH?=-with dev,lint,test,codespell

# Default target executed when no arguments are given to make.
all: help

# Define a variable for the test file path.
TEST_FILE ?= tests/unit_tests/

integration_tests:
	$(POETRY_OR_UV) run pytest tests/integration_tests

test tests:
	$(POETRY_OR_UV) run pytest -v $(TEST_FILE)

all-tests: tests integration_tests

test_watch:
	$(POETRY_OR_UV) run ptw --now . -- tests/unit_tests


######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/experimental --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	$(POETRY_OR_UV) run mypy $(PYTHON_FILES)
	$(POETRY_OR_UV) run black $(PYTHON_FILES) --check
	$(POETRY_OR_UV) run ruff .

claude-lint: lint
	claude -p 'you are a linter. please look at the changes vs. main and report any issues related to typos. report the filename and line number on one line, and a description of the issue on the second line. do not return any other text.'

format format_diff:
	$(POETRY_OR_UV) run black $(PYTHON_FILES)
	$(POETRY_OR_UV) run ruff --select I --fix $(PYTHON_FILES)

spell_check:
	$(POETRY_OR_UV) run codespell --toml pyproject.toml

spell_fix:
	$(POETRY_OR_UV) run codespell --toml pyproject.toml -w


######################
# DOCUMENTATION
######################

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
	$(POETRY_OR_UV) run linkchecker docs/api_reference/_build/html/index.html

######################
# HELP
######################

help:
	@echo '----'
	@echo 'format                       - run code formatters'
	@echo 'lint                         - run linters'
	@echo 'test                         - run unit tests'
	@echo 'tests                        - run unit tests'
	@echo 'test TEST_FILE=<test_file>   - run all tests in file'
	@echo 'test_watch                   - run unit tests in watch mode'
	@echo 'clean                        - run docs_clean and api_docs_clean'
	@echo 'docs_build                   - build the documentation'
	@echo 'docs_clean                   - clean the documentation build artifacts'
	@echo 'docs_linkcheck               - run linkchecker on the documentation'
	@echo 'api_docs_build               - build the API Reference documentation'
	@echo 'api_docs_clean               - clean the API Reference documentation build artifacts'
	@echo 'api_docs_linkcheck           - run linkchecker on the API Reference documentation'
	@echo 'spell_check               	- run codespell on the project'
	@echo 'spell_fix               		- run codespell on the project and fix the errors'


.PHONY: dist
dist:
	$(POETRY_OR_UV) build

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
release: validate integration_tests clean dist
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

## Start jupyter
jupyter:
	poetry run jupyter lab

## Validate the code
validate: $(POETRY_OR_UV).lock format lint spell_check test


_poetry-init:
	@poetry self update
	@poetry self add poetry-dotenv-plugin
	@poetry self add poetry-plugin-export
	@poetry self add poetry-git-version-plugin
	@poetry config virtualenvs.in-project true
	@poetry install --sync $(POETRY_EXTRA) --with $(POETRY_WITH)

_uv-init:
	@uv sync $(UV_GROUP)

init: _$(POETRY_OR_UV)-init
#	@pre-commit install
	@git lfs install