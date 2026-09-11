SHELL=/bin/bash
.PHONY: all format format_diff lint lint_diff claude-lint test tests coverage \
	unit-tests integration-tests container-tests sample-tests all-tests gh-tests \
	spell_check spell_fix clean extra-clean help \
	api_docs_build api_docs_clean api_docs_linkcheck \
	build-images build-image-base build-image-landlock build-image-unshare build-image-bwrap build-image-qemu build-image-docker build-image-podman build-image-clean \
	minikube-ready minikube-build-images lock validate _uv-init devpi-deploy inspector github-push-test init

UV_GROUP?=--group dev --group test --group lint

# Use cursor-agent, claude, etc.
LLM_CLI?=cursor-agent

# Default target executed when no arguments are given to make.
all: help

.vscode/launch.json: .idea/runConfigurations/*
	$(LLM_CLI) -p "Update the .vscode/launch.json file with the modification of the files in .idea/runConfigurations/"

.PHONY: fix-vs-code
# Fix VS Code launch.json
fix-vs-code: .vscode/launch.json


###############
# TEMPLATE COMPRESSION
###############

# Generic rule: convert *.template.md to *.md with caveman ultra compression via API
%.md: %.template.md
	@uv run python3 scripts/compress_template.py $< $@

# Compress AGENTS.md from template
AGENTS.md: AGENTS.template.md

# Compress all templates. Each compression is an API call, so they must not run
# concurrently: the templates are listed in a single recipe rather than as
# parallel prerequisites (make 4.3 ignores .NOTPARALLEL's arguments and would
# serialize the whole Makefile).
TEMPLATES = $(patsubst %.template.md,%.md,$(wildcard *.template.md))
.PHONY: compress-templates
compress-templates:
	@for target in $(TEMPLATES); do $(MAKE) --no-print-directory $$target || exit 1; done

## Make unit test
unit-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest -v tests/unit_tests/

# Ensure minikube is running (start if installed but not running).
# When we start minikube, wait for node and CoreDNS so pods get DNS (avoids "name resolution" failures).
minikube-ready:
	@command -v minikube >/dev/null 2>&1 && (minikube status >/dev/null 2>&1 || (minikube start && kubectl wait --for=condition=Ready nodes --all --timeout=120s 2>/dev/null && (kubectl wait --for=condition=Ready pod -l k8s-app=kube-dns -n kube-system --timeout=120s 2>/dev/null || true))) || true

# Build all provider images into minikube's Docker (no-op if minikube is missing or not running).
minikube-build-images:
	@if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then \
	  eval $$(minikube docker-env) && $(MAKE) build-image-docker; \
	fi

## Make docker/podman/kubernetes tests (builds python-sb:latest from dist/ if needed). Use OS_SANDBOX (default: unshare).
container-tests: build-images
	$(MAKE) minikube-ready
	$(MAKE) minikube-build-images
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && OS_SANDBOX=$${OS_SANDBOX:-unshare} uv run pytest -v tests/containers_tests/

## Make integration tests
integration-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest tests/integration_tests

# (integration first: the unit tests leave the socket guard
# armed with a deny-all rule set, which breaks the in-process integration tests).
# Only the parent process is measured: the sandbox is whitelist-only, so coverage's
# own environment variables never reach the sandboxed child.
## Report test coverage
coverage:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest tests/integration_tests tests/unit_tests --cov=pysandboxes --cov-report=term --cov-report=html

# Uncomment a sample only once it satisfies the acceptance criteria of
# the samples design spec
# Order of treatment: mcp-server-demo, then mcp-client-demo, then the frameworks.
SAMPLES = \
	agno \
	autogen \
	crewai \
	google-adk \
	langchain \
	langgraph \
	mcp-client \
	mcp-server \
	openai-agents-sdk \
	pydantic-ai \
	smolagents \
	strands-agents

# One target per sample, so `make -jN sample-tests` runs the suites
# concurrently. Each sample has its own pyproject.toml, uv.lock and venv, and
# $(MAKE) shares the jobserver, so -jN stays a global budget.
# The per-sample targets must not be declared .PHONY: make skips the implicit
# rule search for phony targets, which would leave this pattern rule unused.
sample-tests-%:
	$(MAKE) -C samples/$*-demo tests

## Make the samples' own test suites
# Run every sample even when one fails, and still exit non-zero if any did:
# stopping at the first failure hides the state of the samples behind it, and
# a run of twelve suites is worth reporting in full. `-k` is what gives both
# halves of that -- keep going, then fail -- and it inherits the jobserver, so
# `make -jN sample-tests` stays parallel.
sample-tests:
	@$(MAKE) -k $(addprefix sample-tests-,$(SAMPLES))


## Make github tests locally
gh-tests: lint
	if [ -f .local.py-sandboxes ]; then mv .local.py-sandboxes .local.py-sandboxes.backup; fi
	gh act push
	if [ -f .local.py-sandboxes.backup ]; then mv .local.py-sandboxes.backup .local.py-sandboxes; fi

## Make all tests
all-tests: unit-tests integration-tests container-tests sample-tests

########################
# LINTING AND FORMATTING
########################

# Define a variable for Python and notebook files.
PYTHON_FILES=pysandboxes/ tests/
lint_diff format_diff: PYTHON_FILES=$(shell git diff --name-only --diff-filter=d develop -- '*.py' '*.ipynb')

# lint only checks: it must never rewrite the sources, otherwise `black --check`
# would always pass. Run `make format` to fix what lint reports.
# The *_diff variants get an empty file list when the branch has no Python
# change, so the guard keeps the tools from running on the whole tree.
lint lint_diff:
	@FILES="$(PYTHON_FILES)"; \
	if [ -z "$$FILES" ]; then echo "lint: no Python file to check."; else \
		set -e -x; \
		unset VIRTUAL_ENV; uv run mypy $$FILES; \
		uvx pyright $$FILES; \
		uvx black --check $$FILES; \
		uvx ruff check $$FILES; \
	fi

claude-lint: lint
	claude -p 'you are a linter. please look at the changes vs. main and report any issues related to typos. report the filename and line number on one line, and a description of the issue on the second line. do not return any other text.'

format format_diff:
	@FILES="$(PYTHON_FILES)"; \
	if [ -z "$$FILES" ]; then echo "format: no Python file to format."; else \
		set -e -x; \
		uvx black $$FILES; \
		uvx ruff check --select I --fix $$FILES; \
	fi

spell_check:
	uvx codespell --toml pyproject.toml

spell_fix:
	uvx codespell --toml pyproject.toml -w

extra-clean:
	@rm -f .zshrc .bashrc .profile .zprofile .bash_profile .gitconfig .ripgreprc .git/config.lock .gitmodules || true

# Clean the environment
clean: api_docs_clean extra-clean
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} \; || true
	@rm -Rf dist/ .make-* .mypy_cache .pytest_cache .ruff_cache
	@rm -f denied-write.probe || true

# pdoc imports the package to introspect it, so it runs inside the project
# environment (`--with` adds pdoc itself without touching pyproject.toml).
# The public API reaches the caller through a module-level __getattr__ (lazy
# loading), so the __all__ names are absent from pysandboxes.__dict__ -- the
# only place pdoc looks. Reading each name once binds it in the module before
# pdoc introspects, so the API is documented instead of being reported as an
# unresolvable submodule.
## Generate the API documentation from the docstrings into docs/api/
api_docs_build:
	unset VIRTUAL_ENV && uv run --with pdoc python -c \
	  'import pysandboxes as p; [setattr(p, n, getattr(p, n)) for n in p.__all__]; from pdoc.__main__ import cli; cli()' \
	  pysandboxes --docformat google -o docs/api

api_docs_clean:
	rm -rf docs/api

api_docs_linkcheck: api_docs_build
	uvx linkchecker docs/api/index.html

######
# HELP
######

.DEFAULT_GOAL := help
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
	  	-f Dockerfile . || exit 1; \
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
	  	-f Dockerfile-landlock . || exit 1; \
	done; \
	touch .make-build-image-landlock


.make-build-image-unshare: .make-build-image-base Dockerfile-unshare
	@for CONTAINER_CMD in podman docker; do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb-unshare:$(PYTHON_VERSION), python-sb-unshare:latest with $$CONTAINER_CMD..."; \
	  $$CONTAINER_CMD build \
	  	--build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	-t python-sb-unshare:$(PYTHON_VERSION) \
	  	-t python-sb-unshare:latest \
	  	-t python-sb-unshare:unshare \
	  	-f Dockerfile-unshare . || exit 1; \
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
	  	-f Dockerfile-bwrap . || exit 1; \
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
	  	-f Dockerfile-qemu . || exit 1; \
	done; \
	touch .make-build-image-qemu

# Build base image python-sb (Python + wheel); required by all provider images below
build-image-base: .make-build-image-base

# Build landlock image (FROM python-sb): python-sb-landlock:$(PYTHON_VERSION), python-sb-landlock:latest
build-image-landlock: .make-build-image-landlock

# Build unshare image (FROM python-sb): python-sb-unshare:$(PYTHON_VERSION), python-sb-unshare:latest
build-image-unshare: .make-build-image-unshare

# Build bwrap image (FROM python-sb): python-sb-bwrap:$(PYTHON_VERSION), python-sb-bwrap:latest
build-image-bwrap: .make-build-image-bwrap

# Build qemu image (FROM python-sb): python-sb-qemu:$(PYTHON_VERSION), python-sb-qemu:latest
build-image-qemu: .make-build-image-qemu

## Build all provider images (and base first); see dependency graph above (e.g. minikube: eval $(minikube docker-env) && make build-image-docker)
build-images: Dockerfile .make-dist \
	.make-build-image-base \
	.make-build-image-landlock \
	.make-build-image-unshare \
	.make-build-image-bwrap \
	.make-build-image-qemu

IMAGE_STAMPS := .make-build-image-base .make-build-image-landlock .make-build-image-unshare .make-build-image-bwrap .make-build-image-qemu

# The sentinels say "built", never "built *where*", so they are dropped on both sides:
# before, because they record a build against the previous daemon and would leave every
# image unbuilt here; after, because they would otherwise credit this daemon's images to
# the next local build, which would skip it and run the tests against images that only
# exist in minikube.
# Build all provider images into the current Docker daemon (use after: eval $(minikube docker-env))
build-image-docker:
	@rm -f $(IMAGE_STAMPS)
	@$(MAKE) build-images
	@rm -f $(IMAGE_STAMPS)

# Same as build-images (podman then docker in each recipe); named for symmetry with build-image-docker
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
# uv publish is not interactive: it reads the API token from UV_PUBLISH_TOKEN
# (set it in the shell or in .env), unlike twine which used to prompt.
define _check-publish-token
	@set -a && if [ -f .env ]; then source .env; fi && \
	if [ -z "$$UV_PUBLISH_TOKEN" ]; then \
		echo "UV_PUBLISH_TOKEN is not set: export the $(1) API token before publishing."; \
		exit 1; \
	fi
endef

.PHONY: test-publish
## Publish distribution on test.pypi.org
test-publish: .make-dist
ifeq ($(OFFLINE),True)
	@echo "Can not test-publish in offline mode"
else
	$(call _check-publish-token,test.pypi.org)
	@rm -f dist/*.asc
	set -a && if [ -f .env ]; then source .env; fi && \
	uv publish --publish-url https://test.pypi.org/legacy/
endif

# ---------------------------------------------------------------------------------------
# Snippet to publish the release to pypi.org.
# clean removes dist/ and the .make-* sentinels, so the distribution is rebuilt
# from the recipe instead of being a prerequisite: as a prerequisite it would
# race with clean under `make -j`.
.PHONY: release
## Publish distribution on pypi.org
release: validate all-tests
ifeq ($(OFFLINE),True)
	@echo "Can not release in offline mode"
else
	$(call _check-publish-token,pypi.org)
	$(MAKE) clean
	$(MAKE) dist
	[[ $$( find dist -name "*.dev*" | wc -l ) == 0 ]] || \
		( echo "Add a tag version in GIT before release" \
		; exit 1 )
	rm -f dist/*.asc
	set -a && if [ -f .env ]; then source .env; fi && \
	uv publish
endif

uv.lock: pyproject.toml
	uv lock
	git add uv.lock
	unset VIRTUAL_ENV && uv sync $(UV_GROUP)


## Refresh lock
lock: uv.lock

# format is not a prerequisite: it rewrites the sources, which would make the
# `black --check` inside lint pass unconditionally.
## Validate the code
validate: uv.lock lint spell_check unit-tests


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
	 uv pip install -i $(PIP_INDEX_URL) .

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



### DEBUG ###

.PHONY: get-new-version publish-patch publish-minor

# Helper target to calculate next version
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

