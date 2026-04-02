SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration-tests docker_tests help extended_tests build-image build-image-docker build-image-clean minikube-ready

# Switch to poetry to uv
UV_GROUP?=--group dev --group test --group lint

POETRY_EXTRA?=
POETRY_WITH?=-with dev,lint,test,codespell

# Use cursor-agent, claude, etc.
LLM_CLI?=cursor-agent

# Default target executed when no arguments are given to make.
all: help

.vscode/launch.json: .idea/runConfigurations/*
	$(LLM_CLI) -p "Update the .vscode/launch.json file with the modification of the files in .idea/runConfigurations/"

.PHONY: fix-vs-code
# Fix VS Code launch.json
fix-vs-code: .vscode/launch.json


.PHONY: fix-gemini
.gemini/commands/*: .ia/commands/*.md scripts/update_gemini_cmd.py
	uv run ./scripts/update_gemini_cmd.py

fix-gemini: .gemini/commands/*

.env:

## Make unit test
unit-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest -v tests/unit_tests/

## Ensure minikube is running (start if installed but not running).
## When we start minikube, wait for node and CoreDNS so pods get DNS (avoids "name resolution" failures).
minikube-ready:
	@command -v minikube >/dev/null 2>&1 && (minikube status >/dev/null 2>&1 || (minikube start && kubectl wait --for=condition=Ready nodes --all --timeout=120s 2>/dev/null && (kubectl wait --for=condition=Ready pod -l k8s-app=kube-dns -n kube-system --timeout=120s 2>/dev/null || true))) || true

## Make docker/podman/kubernetes tests (builds python-sb:latest from dist/ if needed)
container-tests: build-image
#	tests/containers/test-podman.sh
#	tests/containers/test-docker.sh
	$(MAKE) minikube-ready
	tests/containers/test-kubernetes.sh

## Make integration tests
integration-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest tests/integration_tests

## Make integration tests
sample-tests:
	# (cd samples/mcp-client && make tests && true)
	# (cd samples/mcp-server && make tests && true)

## Make github tests locally
gh-tests: format lint
	if [ -f .local.py-sandboxes ]; then mv .local.py-sandboxes .local.py-sandboxes.backup; fi
	gh act push
	if [ -f .local.py-sandboxes.backup ]; then mv .local.py-sandboxes.backup .local.py-sandboxes; fi

## Make all tests
all-tests: unit-tests integration-tests container-tests sample-tests

test_watch:
	unset VIRTUAL_ENV && uv run ptw --now . -- tests/unit_tests


########################
# LINTING AND FORMATTING
########################

# Define a variable for Python and notebook files.
PYTHON_FILES=pysandboxes/ tests/
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/experimental --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint: format
	unset VIRTUAL_ENV && uv run mypy $(PYTHON_FILES)
	uvx pyright $(PYTHON_FILES)
	uvx black --check $(PYTHON_FILES)
	uvx ruff check $(PYTHON_FILES)

claude-lint: lint
	claude -p 'you are a linter. please look at the changes vs. main and report any issues related to typos. report the filename and line number on one line, and a description of the issue on the second line. do not return any other text.'

format format_diff:
	uvx black $(PYTHON_FILES)
	uvx ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	uvx codespell --toml pyproject.toml

spell_fix:
	uvx codespell --toml pyproject.toml -w


###############
# DOCUMENTATION
###############

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
	unset VIRTUAL_ENV && uv run linkchecker docs/api_reference/_build/html/index.html

######
# HELP
######

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



# Build inputs: rebuild dist/ when any of these change.
BUILD_SOURCES = pyproject.toml README.md $(shell find pysandboxes -type f \( -name '*.py' -o -name '*.toml' \) 2>/dev/null)

# Sentinel updated after a successful build; dist depends on it so we only run uv build when sources are newer.
.make-dist: $(BUILD_SOURCES)
	uv build
	@touch .make-dist

## Build distribution (wheel/sdist); only runs when pyproject.toml, README.md or pysandboxes sources changed.
.PHONY: dist
dist: .make-dist

# ---------------------------------------------------------------------------------------
# Image python-sb:$(PYTHON_VERSION), with tag python-sb:latest added (wheel from dist/).
# Rebuild only if image missing or Dockerfile/wheel newer than image.
# Builds one image in Podman and one in Docker. PYTHON_VERSION is taken from uv's current Python.
PYTHON_VERSION := $(shell uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11")
IMAGE_TAG_VERSION := python-sb:$(PYTHON_VERSION)
IMAGE_NAME := python-sb:latest

.make-build-image: Dockerfile .make-dist
	@WHEEL="$$(find dist -maxdepth 1 -name '*.whl' -print -quit)"; \
	if [ -z "$$WHEEL" ]; then echo "No wheel in dist/"; exit 1; fi; \
	DOCKERFILE_TS=$$(stat -c %Y Dockerfile 2>/dev/null); \
	WHEEL_TS=$$(stat -c %Y "$$WHEEL" 2>/dev/null); \
	for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  NEED_REBUILD=0; \
	  if ! $$CONTAINER_CMD image inspect $(IMAGE_NAME) >/dev/null 2>&1; then \
	    echo "Image $(IMAGE_NAME) missing for $$CONTAINER_CMD, building..."; \
	    NEED_REBUILD=1; \
	  else \
	    echo "Checking if image $(IMAGE_NAME) needs rebuild ($$CONTAINER_CMD)..."; \
	    IMAGE_TS=$$($$CONTAINER_CMD image inspect -f '{{.Created}}' $(IMAGE_NAME) 2>/dev/null | xargs -I {} date -d "{}" +%s 2>/dev/null || echo "0"); \
	    [ -n "$$DOCKERFILE_TS" ] && [ "$$DOCKERFILE_TS" -gt "$$IMAGE_TS" ] 2>/dev/null && NEED_REBUILD=1; \
	    [ -n "$$WHEEL_TS" ] && [ "$$WHEEL_TS" -gt "$$IMAGE_TS" ] 2>/dev/null && NEED_REBUILD=1; \
	  fi; \
	  if [ "$$NEED_REBUILD" = "1" ]; then \
	    echo "Building $(IMAGE_TAG_VERSION) (and $(IMAGE_NAME)) with $$CONTAINER_CMD (Python $(PYTHON_VERSION))..."; \
	    $$CONTAINER_CMD build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -t $(IMAGE_TAG_VERSION) -t $(IMAGE_NAME) -f Dockerfile .; \
	  fi; \
	done; \
	touch .make-build-image

## Build image python-sb:$(PYTHON_VERSION) and tag python-sb:latest (only if wheel or Dockerfile newer than each image)
build-image: .make-build-image

## Build image with docker only (for minikube: eval $(minikube docker-env) && make build-image-docker)
build-image-docker: Dockerfile .make-dist
	@WHEEL="$$(find dist -maxdepth 1 -name '*.whl' -print -quit)"; \
	if [ -z "$$WHEEL" ]; then echo "No wheel in dist/"; exit 1; fi; \
	echo "Building $(IMAGE_TAG_VERSION) (and $(IMAGE_NAME)) with docker (Python $(PYTHON_VERSION))..."; \
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -t $(IMAGE_TAG_VERSION) -t $(IMAGE_NAME) -f Dockerfile .

## Prune container build caches and force full rebuild
build-image-clean:
	@echo "Pruning build caches and forcing rebuild..."
	@command -v docker >/dev/null 2>&1 && docker builder prune -f || true
	@command -v podman >/dev/null 2>&1 && (podman builder prune -f 2>/dev/null || podman system prune -f 2>/dev/null) || true
	@rm -f .make-build-image
	@$(MAKE) build-image

# ---------------------------------------------------------------------------------------
# Snippet to test publishing a distribution to test.pypi.org.
.PHONY: test-twine
## Publish distribution on test.pypi.org
test-twine: .make-dist
ifeq ($(OFFLINE),True)
	@echo -e "$(red)Can not test-twine in offline mode$(normal)"
else
	@$(VALIDATE_VENV)
	rm -f dist/*.asc
	twine upload --sign --repository-url https://test.pypi.org/legacy/ \
		$(shell find dist -type f \( -name "*.whl" -or -name '*.gz' \) -and ! -iname "*dev*" )
endif

# ---------------------------------------------------------------------------------------
# Snippet to publish the release to pypi.org.
.PHONY: release
## Publish distribution on pypi.org
release: validate all-tests clean .make-dist
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

uv.lock: pyproject.toml
	uv lock
	git add uv.lock
	unset VIRTUAL_ENV && uv sync $(UV_GROUP)


## Refresh lock
lock: $(LOCK)

## Validate the code
validate: uv.lock format lint spell_check all-tests


_uv-init:
	@uv sync $(UV_GROUP)


# Variables for the devpi environment
DEVPI_URL := http://localhost:3141
PIP_INDEX_URL=http://localhost:3141/$(USER)/dev
UV_INDEX=http://localhost:3141/$(USER)/dev
# User credentials (Adjust these or export them via 'export' from the shell)
DEVPI_USER := $(USER)
DEVPI_PASS := 123

.PHONY: devpi-start devpi-stop devpi-web devpi-install-devpi

.devpi:
	@echo "--- 🛠️ Initializing User and Index ---"
	@devpi-init --serverdir .devpi  --role master
	@devpi-server --serverdir .devpi > /dev/null 2>&1 & echo $$!>.devpi/devpi.pid
	@sleep 3
	@devpi use $(DEVPI_URL)
	@devpi user -c $(DEVPI_USER) password=$(DEVPI_PASS)
	@devpi login $(DEVPI_USER) --password=$(DEVPI_PASS)
	@devpi index -c dev bases=root/pypi
	@$(MAKE) devpi-stop
	@echo "✅ devpi initialized."

## Start Devpi server
devpi-start: .devpi
	@if [ ! -f ".devpi/devpi.pid" ]; then \
		devpi-server --serverdir .devpi > /dev/null 2>&1 & echo $$!>.devpi/devpi.pid ; \
		echo "✅ devpi-server started." ;\
	fi

devpi-stop:
	@if [ -f ".devpi/devpi.pid" ]; then \
		PID=$$(cat .devpi/devpi.pid); \
		kill $$PID; \
		rm .devpi/devpi.pid; \
		echo "devpi Server (PID $$PID) stopped."; \
	else \
		echo "PID file not found. Please stop the devpi-server process manually if necessary."; \
	fi

## Start Devpi console
devpi-web:
	xdg-open $(PIP_INDEX_URL)

devpi-install-devpi:
	 uv pip install -i $(REPO) .

devpi-deploy:
	uv build
	devpi upload

## Start MCP inspector
inspector:
	npx @modelcontextprotocol/inspector

github-push-test:
	gh act push

init: _uv-init
#	@pre-commit install
	gh extension install https://github.com/nektos/gh-act
	@git lfs install 2>/dev/null || true


### RELEASE ###

.PHONY: get-new-version publish-patch publish-minor prepare-future-changelog

## Helper target to calculate next version
get-new-version:
	@CURRENT_VERSION=$$(python -c "import importlib.metadata; print(importlib.metadata.version('pysandboxes'))"); \
	MAJOR=$$(echo $$CURRENT_VERSION | cut -d. -f1); \
	MINOR=$$(echo $$CURRENT_VERSION | cut -d. -f2); \
	PATCH=$$(echo $$CURRENT_VERSION | cut -d. -f3); \
	if [ "$(BUMP)" = "patch" ]; then \
		echo "$$MAJOR.$$MINOR.$$((PATCH+1))"; \
	elif [ "$(BUMP)" = "minor" ]; then \
		echo "$$MAJOR.$$((MINOR+1)).0"; \
	else \
		echo "Error: BUMP variable must be 'patch' or 'minor'" >&2; \
		exit 1; \
	fi

# Function to check if git working directory is clean
define _check_git_status
	@if ! git diff-index --quiet HEAD --; then \
		echo "Git working directory is not clean. Please commit or stash your changes."; \
		exit 1; \
	fi
endef

# Function to check if git branch is develop
define _check_git_branch
	@if [ `git rev-parse --abbrev-ref HEAD` != "develop" ]; then \
		echo "You must be on the 'develop' branch to publish a release."; \
		exit 1; \
	fi
endef

# Function to prepare the changelog with a specific version
define _prepare-changelog
	echo "Starting changelog preparation..."; \
	NEW_VERSION=$$(make --no-print-directory -s get-new-version BUMP=$(1)); \
	TODAY_DATE=$$(date +%Y-%m-%d); \
	echo "Updating CHANGELOG.md to version $$NEW_VERSION ($$TODAY_DATE)"; \
	SEARCH_PATTERN="## \[0\.0\.0\] - 202.-XX-XX"; \
	REPLACE_PATTERN="## [$$NEW_VERSION] - $$TODAY_DATE"; \
	sed -i "s/$$SEARCH_PATTERN/$$REPLACE_PATTERN/" CHANGELOG.md; \
	echo "CHANGELOG.md updated successfully."
endef

# Function to update version and tag
define _update-and-tag-version
	echo "Committing and tagging version..."; \
	NEW_VERSION=$$(make --no-print-directory -s get-new-version BUMP=$(1)); \
	git add CHANGELOG.md; \
	git commit -m "Release v$$NEW_VERSION"; \
	git tag -a "v$$NEW_VERSION" -m "Release v$$NEW_VERSION"; \
	echo "Tagged version v$$NEW_VERSION"
endef

# Function to prepare future changelog entry
define _prepare-future-changelog
	echo "Preparing future changelog entry..."; \
	FIRST_VERSION=$$(grep -m 1 -oP '## \[\K[0-9]+\.[0-9]+\.[0-9]+' CHANGELOG.md); \
	echo "Inserting new entry before version $$FIRST_VERSION..."; \
	SEARCH_LINE="## \[$$FIRST_VERSION\]"; \
	NEW_ENTRY="## [0.0.0] - 202X-XX-XX\n"; \
	sed -i "/$$SEARCH_LINE/i $$NEW_ENTRY" CHANGELOG.md; \
	echo "Future changelog entry added."
endef

# Function to publish release on GitHub
define _publish-github-release
	NEW_VERSION=$$(make --no-print-directory -s get-new-version BUMP=$(1)); \
	TAG="v$$NEW_VERSION"; \
	rm -Rf ./dist/*; \
	uv build ;\
	gh release create --draft $$TAG ./dist/* --title "$(2)" --notes-file CHANGELOG.md; \
	echo "Release $$TAG would be published on GitHub with title: $(2)"
endef

## Publish a patch release (complete workflow)
publish-patch:
	@echo "=== Starting PATCH release workflow ==="
	@echo ""
	$(call _check_git_status)
	$(call _check_git_branch)
	@echo "Enter the release title (e.g., v0.0.1 - Bug fixes):"
	@read -r RELEASE_TITLE; \
	if [ -z "$$RELEASE_TITLE" ]; then \
		echo "Title is required. Aborting release."; \
		exit 1; \
	fi; \
	echo ""; \
	echo "Step 1/7: Merge in master..."; \
	git checkout master; \
	git merge --allow-unrelated-histories develop -m "Merge from develop"; \
	echo ""; \
	echo "Step 2/7: Preparing changelog..."; \
	$(call _prepare-changelog,patch); \
	echo ""; \
	echo "Step 3/7: Committing and tagging..."; \
	$(call _update-and-tag-version,patch); \
	echo ""; \
	echo "Step 4/7: Publishing to GitHub..."; \
	git push origin master; \
	git push origin v$$NEW_VERSION; \
	$(call _publish-github-release,patch,$$RELEASE_TITLE); \
	echo ""; \
	echo "Step 5/7: Return to develop..."; \
	git checkout develop; \
	git merge master -m "Merge from master"; \
	echo ""; \
	echo "Step 6/7: Preparing future changelog..."; \
	$(call _prepare-future-changelog); \
	echo "Step 7/7: Commit future changelog..."; \
	git add CHANGELOG.md; \
	git commit -m "Preparing future changelog" ; \
	echo "=== PATCH draft release $$RELEASE_TITLE workflow completed successfully ==="

## Publish a minor release (complete workflow)
publish-minor:
	@echo "=== Starting MINOR release workflow ==="
	@echo ""
	$(call _check_git_status)
	$(call _check_git_branch)
	@echo "Enter the release title (e.g., v0.1.0 - new features):"
	@read -r RELEASE_TITLE; \
	if [ -z "$$RELEASE_TITLE" ]; then \
		echo "Title is required. Aborting release."; \
		exit 1; \
	fi; \
	echo ""; \
	echo "Step 1/7: Merge in master..."; \
	git checkout master; \
	git merge --allow-unrelated-histories develop -m "Merge from develop"; \
	echo ""; \
	echo "Step 2/7: Preparing changelog..."; \
	$(call _prepare-changelog,minor); \
	echo ""; \
	echo "Step 3/7: Committing and tagging..."; \
	$(call _update-and-tag-version,minor); \
	echo ""; \
	echo "Step 4/7: Publishing to GitHub..."; \
	git push origin master; \
	git push origin v$$NEW_VERSION; \
	$(call _publish-github-release,minor,$$RELEASE_TITLE); \
	echo ""; \
	echo "Step 5/7: Return to develop..."; \
	git checkout develop; \
	git merge master -m "Merge from master"; \
	echo ""; \
	echo "Step 6/7: Preparing future changelog..."; \
	$(call _prepare-future-changelog); \
	echo "Step 7/7: Commit future changelog..."; \
	git add CHANGELOG.md; \
	git commit -m "Preparing future changelog" ; \
	echo "=== MINOR draft release $$RELEASE_TITLE workflow completed successfully ==="
