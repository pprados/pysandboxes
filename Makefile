SHELL=/bin/bash
.PHONY: all format lint test tests test_watch integration-tests docker_tests help extended_tests build-image build-images build-image-base build-image-landlock build-image-unshare build-image-bwrap build-image-qemu build-image-docker build-image-podman build-image-clean minikube-ready minikube-build-images init sync-rules

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


###############
# TEMPLATE COMPRESSION
###############

# Generic rule: convert *.template.md/.mdc to *.md with caveman ultra compression via API
%.md: %.template.md
	@uv run python3 scripts/compress_template.py $< $@

%.md: %.template.mdc
	@uv run python3 scripts/compress_template.py $< $@

## Compress AGENTS.md from template
AGENTS.md: AGENTS.template.md

## Compress all .ai/rules/*.md from templates (.template.md and .template.mdc)
.ai/rules/%.md: .ai/rules/%.template.md
.ai/rules/%.md: .ai/rules/%.template.mdc

# Compress all templates (AGENTS + rules)
.NOTPARALLEL: compress-templates
.PHONY: compress-templates
compress-templates: AGENTS.md $(patsubst .ai/rules/%.template.md,.ai/rules/%.md,$(wildcard .ai/rules/*.template.md)) $(patsubst .ai/rules/%.template.mdc,.ai/rules/%.md,$(wildcard .ai/rules/*.template.mdc))

## Make unit test
unit-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest -v tests/unit_tests/

# Ensure minikube is running (start if installed but not running).
# When we start minikube, wait for node and CoreDNS so pods get DNS (avoids "name resolution" failures).
minikube-ready:
	@command -v minikube >/dev/null 2>&1 && (minikube status >/dev/null 2>&1 || (minikube start && kubectl wait --for=condition=Ready nodes --all --timeout=120s 2>/dev/null && (kubectl wait --for=condition=Ready pod -l k8s-app=kube-dns -n kube-system --timeout=120s 2>/dev/null || true))) || true

## Build all provider images into minikube's Docker (no-op if minikube is missing or not running).
minikube-build-images:
	@if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then \
	  eval $$(minikube docker-env) && $(MAKE) build-image-docker; \
	fi

## Make docker/podman/kubernetes tests (builds python-sb:latest from dist/ if needed). Use OS_SANDBOX (default: unshare).
container-tests: build-image
	$(MAKE) minikube-ready
	$(MAKE) minikube-build-images
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && OS_SANDBOX=$${OS_SANDBOX:-unshare} uv run pytest -v tests/containers_tests/

## Make integration tests
integration-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest tests/integration_tests

## Make integration tests
sample-tests:
	(cd samples/mcp-client && make tests && true)
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

.PHONY: dist
## Build distribution (wheel/sdist); only runs when pyproject.toml, README.md or pysandboxes sources changed.
dist: .make-dist

# ---------------------------------------------------------------------------------------
# Docker image dependency graph (each provider Dockerfile uses FROM python-sb:${PYTHON_VERSION}):
#
#   docker.io/library/python:${PYTHON_VERSION}-slim   (upstream; Dockerfile)
#        |
#        +-- python-sb                    Dockerfile ............... build-image-base
#                |
#                +-- python-sb-landlock  Dockerfile-landlock ..... build-image-landlock
#                +-- python-sb-unshare   Dockerfile-unshare ...... build-image-unshare
#                +-- python-sb-bwrap     Dockerfile-bwrap ........ build-image-bwrap
#                +-- python-sb-qemu      Dockerfile-qemu ......... build-image-qemu
#
# Make encodes this: .make-build-image-{landlock,unshare,bwrap,qemu} all prereq .make-build-image-base.
# PYTHON_VERSION from uv. VARIANT = base | landlock | unshare | bwrap | qemu. (firejail not supported in Docker.)
PYTHON_VERSION := $(shell uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11")
VARIANT ?= qemu
# QEMU package per host arch (for build-image-qemu, no script in image)
UNAME_M       := $(shell uname -m)
QEMU_PKG      := $(if $(filter aarch64 arm64,$(UNAME_M)),qemu-system-aarch64,qemu-system-x86)

.make-build-image-base: Dockerfile .make-dist
	@WHEEL="$$(find dist -maxdepth 1 -name '*.whl' -print -quit)"; \
	if [ -z "$$WHEEL" ]; then echo "No wheel in dist/"; exit 1; fi; \
	for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb:$(PYTHON_VERSION), python-sb:latest with $$CONTAINER_CMD (base)..."; \
	  $$CONTAINER_CMD build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	-t python-sb:$(PYTHON_VERSION) \
	  	-t python-sb:subprocess \
	  	-t python-sb:landlock \
	  	-t python-sb:latest \
	  	-f Dockerfile .; \
	done; \
	touch .make-build-image-base

.make-build-image-landlock: .make-build-image-base Dockerfile-landlock
	@for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb-landlock:$(PYTHON_VERSION), python-sb-landlock:latest with $$CONTAINER_CMD..."; \
	  $$CONTAINER_CMD build \
		--build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	-t python-sb-landlock:$(PYTHON_VERSION) \
	  	-t python-sb-landlock:latest \
	  	-t python-sb-landlock:landlock \
	  	-f Dockerfile-landlock .; \
	done; \
	touch .make-build-image-landlock


.make-build-image-unshare: .make-build-image-base Dockerfile-unshare
	for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb-unshare:$(PYTHON_VERSION), python-sb-unshare:latest with $$CONTAINER_CMD..."; \
	  $$CONTAINER_CMD build \
	  	--build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	-t python-sb-unshare:$(PYTHON_VERSION) \
	  	-t python-sb-unshare:latest \
	  	-t python-sb-unshare:unshare \
	  	-f Dockerfile-unshare .; \
	done; \
	touch .make-build-image-unshare

.make-build-image-bwrap: .make-build-image-base Dockerfile-bwrap
	@for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb-bwrap:$(PYTHON_VERSION), python-sb-bwrap:latest with $$CONTAINER_CMD..."; \
	  $$CONTAINER_CMD build \
	  	--build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	-t python-sb-bwrap:$(PYTHON_VERSION) \
	  	-t python-sb-bwrap:latest \
	  	-t python-sb-bwrap:bwrap \
	  	-f Dockerfile-bwrap .; \
	done; \
	touch .make-build-image-bwrap

.make-build-image-qemu: .make-build-image-base Dockerfile-qemu
	@for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb-qemu:$(PYTHON_VERSION), python-sb-qemu:latest with $$CONTAINER_CMD..."; \
	  $$CONTAINER_CMD build \
	  	--build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	--build-arg QEMU_PKG=$(QEMU_PKG) \
	  	-t python-sb-qemu:$(PYTHON_VERSION) \
	  	-t python-sb-qemu:latest \
	  	-t python-sb-qemu:qemu \
	  	-f Dockerfile-qemu .; \
	done; \
	touch .make-build-image-qemu

## Build base image python-sb (Python + wheel); required by all provider images below
build-image-base: .make-build-image-base

## Build landlock image (FROM python-sb): python-sb-landlock:$(PYTHON_VERSION), python-sb-landlock:latest
build-image-landlock: .make-build-image-landlock

## Build unshare image (FROM python-sb): python-sb-unshare:$(PYTHON_VERSION), python-sb-unshare:latest
build-image-unshare: .make-build-image-unshare

## Build bwrap image (FROM python-sb): python-sb-bwrap:$(PYTHON_VERSION), python-sb-bwrap:latest
build-image-bwrap: .make-build-image-bwrap

## Build qemu image (FROM python-sb): python-sb-qemu:$(PYTHON_VERSION), python-sb-qemu:latest
build-image-qemu: .make-build-image-qemu

## Build all sandbox images (base + every provider); same as build-images
build-image: build-images

## Build all provider images (and base first); see dependency graph above (e.g. minikube: eval $(minikube docker-env) && make build-image-docker)
build-images: Dockerfile .make-dist \
	.make-build-image-base \
	.make-build-image-landlock \
	.make-build-image-unshare \
	.make-build-image-bwrap \
	.make-build-image-qemu

## Build all provider images into the current Docker daemon (use after: eval $(minikube docker-env))
build-image-docker: build-images

## Same as build-images (podman then docker in each recipe); named for symmetry with build-image-docker
build-image-podman: build-images

## Prune build caches and force full rebuild of all variants
build-image-clean:
	@echo "Pruning build caches and forcing rebuild..."
	@command -v docker >/dev/null 2>&1 && docker builder prune -f || true
	@command -v podman >/dev/null 2>&1 && (podman builder prune -f 2>/dev/null || podman system prune -f 2>/dev/null) || true
	@rm -f .make-build-image-base .make-build-image-landlock .make-build-image-unshare .make-build-image-bwrap .make-build-image-qemu
	@$(MAKE) build-images

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

## Start Devpi server (local python repo)
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

## Import Packmind packages (if packmind-cli is available and packmind.json exists)
packmind-import:
	@if command -v packmind-cli >/dev/null 2>&1 && [ -f packmind.json ]; then \
		packmind-cli install --recursive ; \
	else \
		true; \
	fi

init: _uv-init
#	@pre-commit install
	gh extension install https://github.com/nektos/gh-act
	@git lfs install 2>/dev/null || true



### DEBUG ###

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

## Synchronize rules from .ai/rules to editor directories
sync-rules:
	@python3 scripts/sync_rules.py
