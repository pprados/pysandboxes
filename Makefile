SHELL=/bin/bash
.PHONY: all format format_diff lint lint_diff claude-lint coverage security-corpus fuzz \
	unit-tests integration-tests container-tests sample-tests sample-tests-matrix all-tests gh-tests gh-all-tests \
	spell_check spell_fix pip-audit pip-audit-all clean extra-clean help \
	api_docs_build api_docs_clean api_docs_linkcheck \
	build-images build-image-base build-image-landlock build-image-unshare build-image-bwrap build-image-qemu build-image-docker build-image-podman build-image-clean \
	minikube-ready minikube-build-images lock validate inspector github-push-test init \
	clean-sandbox-temps quick-demo-gif \
	windows-vm windows-tests windows-tests-all windows-vm-stop windows-vm-clean macos-vm macos-tests macos-vm-stop \
	doctor setup-linux setup-macos setup-windows init-macos-vm

UV_GROUP?=--group dev --group test --group lint
FUZZ_SECONDS?=20
FUZZ_RSS_LIMIT_MB?=1024
FUZZ_TIMEOUT_SECONDS?=5

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

## Run the known Python and transport attack regression corpus
security-corpus:
	uv run pytest -q \
		tests/unit_tests/guard/test_eval_attack_matrix.py \
		tests/unit_tests/guard/test_eval_security_corpus.py \
		tests/unit_tests/guard/test_guard_api.py \
		tests/unit_tests/guard/test_guard_import.py \
		tests/unit_tests/guard/test_guard_escape_fixes.py \
		tests/unit_tests/test_escape_pysandbox.py \
		tests/unit_tests/test_provider_skip_reason.py \
		tests/unit_tests/remote/test_restricted_unpickle.py \
		tests/unit_tests/remote/test_base_sse_daemon_gaps.py \
		tests/integration_tests/test_native_readonly_share.py

## Run a bounded Atheris campaign (Linux x86_64, Python 3.12-3.14; 20s per target)
fuzz:
	@uv run python -c 'import platform, sys; assert sys.implementation.name == "cpython" and (3, 12) <= sys.version_info[:2] < (3, 15) and platform.system() == "Linux" and platform.machine() == "x86_64", "Atheris fuzzing requires CPython 3.12-3.14 on Linux x86_64"'
	@for target in eval_rules eval_transform restricted_pickle sse; do \
		echo "Fuzzing $$target for $(FUZZ_SECONDS)s"; \
		corpus=$$(mktemp -d); \
		cp -R tests/fuzzing/corpus/$$target/. "$$corpus"/; \
		artifact="$${TMPDIR:-/tmp}/pysandboxes-fuzz-artifacts/$$target/"; \
		mkdir -p "$$artifact"; \
		FUZZ_TARGET=$$target uv run --group fuzz python scripts/fuzzing/fuzz_targets.py \
			"$$corpus" -max_total_time=$(FUZZ_SECONDS) -rss_limit_mb=$(FUZZ_RSS_LIMIT_MB) \
			-max_len=4096 -timeout=$(FUZZ_TIMEOUT_SECONDS) -verbosity=0 \
			-artifact_prefix="$$artifact" || { fuzz_exit=$$?; rm -rf "$$corpus"; exit $$fuzz_exit; }; \
		rm -rf "$$corpus"; \
	done

# Ensure minikube is running (start if installed but not running).
# When we start minikube, wait for node and CoreDNS so pods get DNS (avoids "name resolution" failures).
minikube-ready:
	@command -v minikube >/dev/null 2>&1 && (minikube status >/dev/null 2>&1 || (minikube start && kubectl wait --for=condition=Ready nodes --all --timeout=120s 2>/dev/null && (kubectl wait --for=condition=Ready pod -l k8s-app=kube-dns -n kube-system --timeout=120s 2>/dev/null || true))) || true

# Load the provider images built by build-images into minikube (no-op if minikube is missing or not running).
# They are loaded, not rebuilt there: `minikube docker-env` now points at an ssh:// daemon, where buildx
# falls back to its docker-container driver and fails to start BuildKit.
MINIKUBE_IMAGES := python-sb:latest python-sb-landlock:latest python-sb-unshare:latest python-sb-bwrap:latest \
	python-sb-qemu:latest
minikube-build-images: build-images
	@if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then \
	  for IMAGE in $(MINIKUBE_IMAGES); do \
	    echo "Loading $$IMAGE into minikube..."; \
	    minikube image load "$$IMAGE" || exit 1; \
	  done; \
	fi

## Make docker/podman/kubernetes tests (builds python-sb:latest from dist/ if needed). Use OS_SANDBOX (default: unshare).
container-tests: build-images
	$(MAKE) minikube-ready
	$(MAKE) minikube-build-images
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && OS_SANDBOX=$${OS_SANDBOX:-unshare} uv run pytest -v tests/containers_tests/

## Make integration tests
INTEGRATION_TESTS ?= tests/integration_tests
integration-tests:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run pytest $(INTEGRATION_TESTS)

# The cross-os.yml steps, run in a VM: the `subprocess` provider is the only one on macOS and Windows. Three
# processes, as in the workflow: the guard unit tests leave the socket guard armed, which breaks the integration ones.
CROSS_OS_PYTEST = \
	"uv run pytest tests/unit_tests/test_provider_platforms.py" \
	"uv run pytest tests/unit_tests/guard" \
	"uv run pytest -rs -m \"not slow\" tests/integration_tests/test_guards_with_providers.py tests/integration_tests/test_usage_with_providers.py"
# What a VM needs of the checkout: it has no git, so the tracked and new files are streamed as a tar.
VM_SOURCES = git ls-files -co --exclude-standard | tar -cf - -T -
# hatch-vcs reads the version from git, which a VM does not have.
VM_ENV = PYSANDBOXES_FAIL_ON_SKIP=1 SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0

# Keys and disk live under $HOME, out of every checkout and worktree.
WINDOWS_VM_DIR ?= $(HOME)/.pysandboxes/windows-vm
WINDOWS_VM_CONTAINER ?= pysandboxes-windows-vm
WINDOWS_VM_SSH_PORT ?= 2222
WINDOWS_VM_ADMIN ?= Docker
WINDOWS_VM_PYTHON ?= 3.13
WINDOWS_VM_ENGINE ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || (command -v docker >/dev/null 2>&1 && echo docker))
WINDOWS_VM_SSH = ssh -i $(WINDOWS_VM_DIR)/admin -p $(WINDOWS_VM_SSH_PORT) -o IdentitiesOnly=yes \
	-o UserKnownHostsFile=$(WINDOWS_VM_DIR)/known_hosts -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
	$(WINDOWS_VM_ADMIN)@127.0.0.1

## Start the local Windows 11 VM, built with podman or docker (needs /dev/kvm); first boot takes about 30 minutes
windows-vm:
	@set -eu; \
	if [ -z "$(WINDOWS_VM_ENGINE)" ]; then echo "Install Podman or Docker to run the Windows VM." >&2; exit 1; fi; \
	if [ ! -e /dev/kvm ]; then echo "The Windows VM requires /dev/kvm." >&2; exit 1; fi; \
	mkdir -p -m 700 "$(WINDOWS_VM_DIR)/oem" "$(WINDOWS_VM_DIR)/storage"; \
	if [ ! -f "$(WINDOWS_VM_DIR)/admin" ]; then ssh-keygen -q -t ed25519 -N '' -f "$(WINDOWS_VM_DIR)/admin"; fi; \
	cp scripts/windows-vm/install.bat "$(WINDOWS_VM_DIR)/oem/install.bat"; \
	cp "$(WINDOWS_VM_DIR)/admin.pub" "$(WINDOWS_VM_DIR)/oem/admin_authorized_keys"; \
	if $(WINDOWS_VM_ENGINE) container inspect "$(WINDOWS_VM_CONTAINER)" >/dev/null 2>&1; then \
	  $(WINDOWS_VM_ENGINE) start "$(WINDOWS_VM_CONTAINER)" >/dev/null; \
	else \
	  $(WINDOWS_VM_ENGINE) run -d --name "$(WINDOWS_VM_CONTAINER)" --device=/dev/kvm --device=/dev/net/tun --cap-add NET_ADMIN \
	    --stop-timeout 120 -p 127.0.0.1:8006:8006 -p "127.0.0.1:$(WINDOWS_VM_SSH_PORT):22" \
	    -e VERSION=11 -e DISK_SIZE=40G -e RAM_SIZE=4G -e CPU_CORES=4 \
	    -v "$(WINDOWS_VM_DIR)/storage:/storage" -v "$(WINDOWS_VM_DIR)/oem:/oem" docker.io/dockurr/windows >/dev/null; \
	fi; \
	echo "Waiting for the Windows installation and sshd (console: http://127.0.0.1:8006)..."; \
	for attempt in $$(seq 1 180); do \
	  if $(WINDOWS_VM_SSH) -o BatchMode=yes exit >/dev/null 2>&1; then echo "Windows VM reachable on port $(WINDOWS_VM_SSH_PORT)"; exit 0; fi; \
	  sleep 10; \
	done; \
	echo "Timed out waiting for SSH: $(WINDOWS_VM_ENGINE) logs $(WINDOWS_VM_CONTAINER)" >&2; exit 1

WINDOWS_VM_PYTEST ?= $(CROSS_OS_PYTEST)
# As in cross-os.yml, a skipped integration test fails the run; the whole suite skips what Windows cannot run.
WINDOWS_VM_FAIL_ON_SKIP ?= 1

## Run the cross-os.yml test steps in the Windows VM, with the subprocess provider
windows-tests: windows-vm
	@set -u; \
	$(WINDOWS_VM_SSH) "if not exist C:\\pysandboxes mkdir C:\\pysandboxes" || exit 1; \
	$(VM_SOURCES) | $(WINDOWS_VM_SSH) "tar -xf - -C C:/pysandboxes" || exit 1; \
	status=0; \
	for cmd in $(WINDOWS_VM_PYTEST); do \
	  $(WINDOWS_VM_SSH) "cd /d C:\\pysandboxes && set \"PYSANDBOXES_FAIL_ON_SKIP=$(WINDOWS_VM_FAIL_ON_SKIP)\" && set \"SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0\" && uv sync --python $(WINDOWS_VM_PYTHON) --group test && $$cmd" || status=1; \
	done; \
	exit $$status

## Run the whole unit and integration suites in the Windows VM, not only the cross-os.yml steps
windows-tests-all:
	@$(MAKE) windows-tests WINDOWS_VM_FAIL_ON_SKIP=0 WINDOWS_VM_PYTEST='"uv run pytest tests/unit_tests" "uv run pytest tests/integration_tests"'

## Stop the Windows VM, keeping its disk
windows-vm-stop:
	-@$(WINDOWS_VM_ENGINE) stop --time 120 "$(WINDOWS_VM_CONTAINER)" >/dev/null

## Remove the Windows VM, its disk and its keys (destructive); then `make windows-vm` rebuilds it
windows-vm-clean: windows-vm-stop
	@$(WINDOWS_VM_ENGINE) rm -f "$(WINDOWS_VM_CONTAINER)" >/dev/null 2>&1 || true
	rm -rf "$(WINDOWS_VM_DIR)"

# The macOS VM (OSX-KVM, Sonoma, Intel) is built once by `make init-macos-vm` and started by `make macos-vm`. Its
# launcher and its SSH config (host `macos`, port 2223, key id_macos) live in OSX_KVM_DIR. The VM needs uv on its PATH.
OSX_KVM_DIR ?= $(HOME)/.pysandboxes/macos-vm/OSX-KVM
MACOS_PYTHON ?= 3.13
# speckit (test group) pulls numba and llvmlite, which have no macOS x86_64 wheel and fail to build there: nothing
# imports them, so the Intel VM leaves them out. The arm64 runners of cross-os.yml install them.
MACOS_SYNC_SKIP = --no-install-package numba --no-install-package llvmlite
# `uv run` would sync the test group again, with them: it runs against the environment `uv sync` built.
MACOS_UV_RUN = UV_NO_SYNC=1
MACOS_SSH = ssh -F $(OSX_KVM_DIR)/ssh_config -o ConnectTimeout=5 macos

## Start the local macOS VM (OSX-KVM) and wait for SSH
macos-vm:
	@set -u; \
	if $(MACOS_SSH) -o BatchMode=yes exit >/dev/null 2>&1; then echo "macOS VM already reachable"; exit 0; fi; \
	test -x "$(OSX_KVM_DIR)/boot-ssh.sh" || { echo "No $(OSX_KVM_DIR)/boot-ssh.sh: set OSX_KVM_DIR." >&2; exit 1; }; \
	(cd "$(OSX_KVM_DIR)" && nohup ./boot-ssh.sh >boot-ssh.log 2>&1 &); \
	echo "Waiting for the macOS boot..."; \
	for attempt in $$(seq 1 90); do \
	  if $(MACOS_SSH) -o BatchMode=yes exit >/dev/null 2>&1; then echo "macOS VM reachable"; exit 0; fi; \
	  sleep 10; \
	done; \
	echo "Timed out waiting for SSH: see $(OSX_KVM_DIR)/boot-ssh.log" >&2; exit 1

## Run the cross-os.yml test steps in the macOS VM, with the subprocess provider
macos-tests: macos-vm
	@set -u; \
	$(MACOS_SSH) "mkdir -p pysandboxes" || exit 1; \
	$(VM_SOURCES) | $(MACOS_SSH) "tar -xf - -C pysandboxes" || exit 1; \
	status=0; \
	for cmd in $(CROSS_OS_PYTEST); do \
	  $(MACOS_SSH) "export PATH=\$$HOME/.local/bin:\$$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:\$$PATH $(VM_ENV) $(MACOS_UV_RUN) OPENSSL_DIR=\$$HOME/openssl OPENSSL_STATIC=1; cd pysandboxes && uv sync --python $(MACOS_PYTHON) --group test $(MACOS_SYNC_SKIP) && $$cmd" || status=1; \
	done; \
	exit $$status

## Shut the macOS VM down
macos-vm-stop:
	-@$(MACOS_SSH) "sudo -n shutdown -h now" >/dev/null 2>&1 || true

# (integration first: the unit tests leave the socket guard
# armed with a deny-all rule set, which breaks the in-process integration tests).
# The `python-sb` processes the tests start are measured too (`patch = subprocess`, pyproject.toml), and so are
# the sandboxed children of the integration tests: tests/integration_tests/conftest.py gives their profiles the
# coverage settings and a data directory, since the sandbox is whitelist-only. The data lives outside the
# checkout: the profiles expose the checkout read-only, which a writable data directory inside it would contradict.
## Report test coverage
coverage:
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && export COVERAGE_FILE=$${TMPDIR:-/tmp}/pysandboxes-coverage/.coverage && rm -rf $$(dirname $$COVERAGE_FILE) && mkdir -p $$(dirname $$COVERAGE_FILE) && uv run pytest tests/integration_tests tests/unit_tests --cov=pysandboxes --cov-branch --cov-report=term --cov-report=html

# Each mutant runs the whole TESTS list: point TESTS at the module's own tests to go faster.
MUTATION_TESTS ?= tests/unit_tests
MUTATION_JOBS ?= 4
## Mutation testing of one module (cosmic-ray): make mutation MODULE=pysandboxes/guard_socket.py [MUTATION_TESTS=...] [MUTATION_JOBS=4]
mutation:
	@test -n "$(MODULE)" || { echo "Usage: make mutation MODULE=pysandboxes/<module>.py"; exit 1; }
	set -a && if [ -f .env ]; then source .env; fi && unset VIRTUAL_ENV && uv run python scripts/mutation.py $(MODULE) --tests $(MUTATION_TESTS) --jobs $(MUTATION_JOBS)
## Last recorded mutation run of every module, and whether its code changed since: make mutation-status
mutation-status:
	uv run python scripts/mutation.py --status

# Uncomment a sample only once it satisfies the acceptance criteria of its
# design spec.
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
# `init` first: pytest lives in the sample's `test` dependency group, which
# `uv run pytest` does not install -- uv syncs `dev` only. A developer whose
# sample venv was hydrated by an earlier `make init` never notices; a clean
# container fails with `Failed to spawn: pytest`. Two recipe lines rather than
# two goals on one $(MAKE): goals given on a command line run concurrently
# under -jN, which would race `tests` against the sync it depends on.
# UV_GROUP is deliberately not overridden here: the sample Makefile declares it
# with `?=`, so a value pushed from the root would win for a local run too, and
# `uv sync` prunes -- it would strip ipython, pyright and ruff from the venv.
# UV_PYTHON, when set, pins the interpreter for every uv call below -- that is
# what lets the nightly matrix run each sample on each version the project
# claims. A sample whose own requires-python excludes that interpreter is
# skipped, not failed: langgraph-demo is 3.13+, and uv cannot resolve it on
# 3.11. sort -V puts the lower version first, so the sample runs exactly when
# its floor is the lower of the two.
# pytest is run directly rather than through the sample's `tests` target, which
# sources .env: the keys there enable the suites that call a live model and spend
# tokens. The gate variables are also dropped from the caller's environment, and
# pytest-dotenv, which two samples use to load .env on their own, is disabled, so a
# run here skips them exactly as CI does. `make -C samples/<x>-demo tests` still
# reads .env, for a deliberate live run.
LIVE_TEST_GATES = OPENAI_API_KEY RUN_CLAUDE_TESTS
sample-tests-%:
	@req=$$(grep -m1 requires-python samples/$*-demo/pyproject.toml | grep -oE '3\.[0-9]+'); \
	if [ -n "$(UV_PYTHON)" ] && \
	   [ "$$(printf '%s\n%s\n' "$$req" "$(UV_PYTHON)" | sort -V | head -1)" != "$$req" ]; then \
		echo "skip $*-demo: requires-python >= $$req, running $(UV_PYTHON)"; \
	else \
		$(MAKE) -C samples/$*-demo init && \
		cd samples/$*-demo && env $(addprefix -u ,$(LIVE_TEST_GATES)) uv run pytest -p no:dotenv -v tests; \
	fi

# mcp-client spawns the neighbouring server sample as a subprocess, through that
# sample's own interpreter, so that venv has to exist before its suite runs --
# and `mcp-client` sorts before `mcp-server` in SAMPLES. A prerequisite rather
# than an ordering assumption: under -jN nothing else would sequence them. The
# rule carries no recipe, so the pattern rule above still supplies one.
sample-init-%:
	$(MAKE) -C samples/$*-demo init

sample-tests-mcp-client: sample-init-mcp-server

## Make the samples' own test suites
# Run every sample even when one fails, and still exit non-zero if any did:
# stopping at the first failure hides the state of the samples behind it, and
# a run of twelve suites is worth reporting in full. `-k` is what gives both
# halves of that -- keep going, then fail -- and it inherits the jobserver, so
# `make -jN sample-tests` stays parallel.
sample-tests:
	@$(MAKE) -k $(addprefix sample-tests-,$(SAMPLES))

# The release grid: every sample, on every Python the project claims, under every OS provider that confines it,
# which samples.yml runs too. A provider adds limits of its own that a subprocess run cannot show. `none`
# confines nothing, so the confinement scenarios fail there by design; qemu boots a VM per sandbox.
# Pythons outermost: each change of UV_PYTHON rebuilds the sample venvs. Serial: mcp-client's port is fixed.
SAMPLE_PYTHONS = 3.11 3.12 3.13 3.14
SAMPLE_PROVIDERS = subprocess landlock bwrap firejail unshare
## Make the samples' suites on every Python and every OS provider (run before a minor or a given final release)
sample-tests-matrix:
	@status=0; \
	for py in $(SAMPLE_PYTHONS); do for provider in $(SAMPLE_PROVIDERS); do \
		echo "=== samples on Python $$py under $$provider"; \
		UV_PYTHON=$$py OS_SANDBOX=$$provider $(MAKE) sample-tests || status=1; \
	done; done; \
	exit $$status


# `gh act push` alone runs every workflow with a push trigger, whatever its
# branches or tags filter, so the release-only ones would run and fail here. The
# workflows a push on develop triggers are named instead. api-docs.yml is left out:
# it publishes to GitHub Pages, which a local run cannot reach.
GH_PUSH_WORKFLOWS = lint.yml test.yml
# act loads .env into every job by default, which GitHub never does: a key
# there would enable tests the CI skips. It also puts every job on the host
# network, so the parallel rows of a matrix fight over the same fixed ports; a
# bridge network gives each its own stack, as a GitHub runner VM has.
GH_ACT = gh act --env-file /dev/null --network bridge
## Make github tests locally
gh-tests: lint
	if [ -f .local.py-sandboxes ]; then mv .local.py-sandboxes .local.py-sandboxes.backup; fi
	status=0; \
	for w in $(GH_PUSH_WORKFLOWS); do $(GH_ACT) push -W .github/workflows/$$w || status=1; done; \
	if [ -f .local.py-sandboxes.backup ]; then mv .local.py-sandboxes.backup .local.py-sandboxes; fi; \
	exit $$status

# On GitHub, samples.yml and integration.yml are called by full-gate.yml (nightly on develop, release tag) or
# dispatched. The `changes` guard lives in full-gate.yml: dispatched here, they always run, so the local tree
# is always tested.
## Make github tests locally, the scheduled samples and integration workflows included
gh-all-tests: gh-tests
	if [ -f .local.py-sandboxes ]; then mv .local.py-sandboxes .local.py-sandboxes.backup; fi
	$(GH_ACT) workflow_dispatch -W .github/workflows/samples.yml; status=$$?; \
	$(GH_ACT) workflow_dispatch -W .github/workflows/integration.yml || status=1; \
	if [ -f .local.py-sandboxes.backup ]; then mv .local.py-sandboxes.backup .local.py-sandboxes; fi; \
	exit $$status

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

# A vulnerable dev tool cannot reach production, so only the runtime
# dependencies gate `validate`. `pip-audit-all` reports the rest without
# failing, so a dev dependency can still be raised on purpose.
EXPORT_AUDIT=--format requirements-txt --no-emit-project --no-hashes --no-annotate --no-header -q

# Each sample has its own uv.lock. pysandboxes is left out of their export: it is
# an editable path dependency, already audited from the root lock. --frozen audits
# the committed lock as it is, instead of relocking the sample. The export is
# fully pinned, so pip-audit skips resolving it (--no-deps --disable-pip): the
# resolution would run on the root interpreter, which a sample's requires-python
# may exclude. Every sample is audited even when one fails, and the target still
# fails if any did.
#
# crewai imports chromadb unconditionally, and chromadb 1.5.9 carries advisories
# with no fixed release yet. The sample uses neither RAG, memory nor knowledge, so
# they are ignored there only, for now. The matching Dependabot alerts on
# samples/crewai-demo/uv.lock are dismissed as "tolerable risk" for the same reason.
# CrewAI pins mcp~=1.28.1, before the CVE-2026-59951 fix. The sample does not run
# a stateful Streamable HTTP MCP server, which is the affected configuration.
#
# To reactivate, once chromadb publishes a fix:
#   1. drop PIP_AUDIT_IGNORE_crewai below, then relock the sample:
#        uv lock --project samples/crewai-demo --upgrade-package chromadb
#   2. reopen the dismissed alerts, if the relock did not close them:
#        gh api 'repos/pprados/pysandboxes/dependabot/alerts?state=dismissed&package=chromadb' \
#          --jq '.[] | select(.dependency.manifest_path=="samples/crewai-demo/uv.lock") | .number'
#      then, for each number N:
#        gh api -X PATCH repos/pprados/pysandboxes/dependabot/alerts/N -f state=open
#   3. run `make pip-audit`: it must pass without the ignore.
PIP_AUDIT_IGNORE_crewai = --ignore-vuln PYSEC-2026-311 --ignore-vuln PYSEC-2026-3813 \
	--ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815 \
	--ignore-vuln CVE-2026-59951
## Report the runtime dependencies with a known security vulnerability, samples included
pip-audit:
	@unset VIRTUAL_ENV; status=0; \
	echo "== pysandboxes"; \
	uv export $(EXPORT_AUDIT) --no-dev | uv run pip-audit -r /dev/stdin || status=1; \
	$(foreach s,$(SAMPLES), \
		echo "== samples/$(s)-demo"; \
		uv export $(EXPORT_AUDIT) --frozen --no-dev --project samples/$(s)-demo --no-emit-package pysandboxes \
			| uv run pip-audit --no-deps --disable-pip $(PIP_AUDIT_IGNORE_$(s)) -r /dev/stdin || status=1;) \
	exit $$status

## Report the vulnerabilities of every dependency, dev included (never fails)
pip-audit-all:
	-unset VIRTUAL_ENV; uv export $(EXPORT_AUDIT) --all-groups | uv run pip-audit -r /dev/stdin

extra-clean:
	@rm -f .zshrc .bashrc .profile .zprofile .bash_profile .gitconfig .ripgreprc .git/config.lock .gitmodules || true

# Clean the environment
clean: api_docs_clean extra-clean
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} \; || true
	@rm -Rf dist/ .make-* .mypy_cache .pytest_cache .ruff_cache
	@rm -f denied-write.probe || true
	@$(MAKE) --no-print-directory clean-sandbox-temps

# A sandboxed run leaves temporary files in the repository root, not under /tmp:
# once the guards are armed /tmp is unreachable, and tempfile.gettempdir() falls
# back to the working directory (see the note at main_sandbox.py:468). The DNS
# and hosts files unshare_setup.py writes are bind-mounted into the sandbox, so
# they carry delete=False and nobody unlinks them afterwards -- a full sample or
# integration run drops dozens, and they add up until the disk complains.
# Restricted to the shapes tempfile produces, so the tracked `tmp/` directory and
# anything a developer named `tmpfoo` by hand are left alone.
## Remove the temporary files a sandboxed run leaves behind
clean-sandbox-temps:
	@find . -maxdepth 1 \( \
		-type f \( -name 'tmp??????*.hosts' -o -name 'tmp??????*.resolv' \) -o \
		-type d -name 'tmp??????' \
	\) -exec rm -rf {} + 2>/dev/null || true

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
# The version carries the git describe output, so building at two commits leaves two
# wheels behind. The image Dockerfiles install dist/*.whl as a whole, and pip refuses
# the two versions of the same package, so drop the previous build first.
.make-dist: $(BUILD_SOURCES)
	@rm -f dist/*.whl dist/*.tar.gz
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
# PYTHON_VERSION from uv. VARIANT = base | landlock | unshare | bwrap | qemu.
# No firejail: inside a container it runs unconfined, even with --privileged and --force.
PYTHON_VERSION := $(shell uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11")
VARIANT ?= qemu
# Container engines the images are built with, when installed; CI builds one per runner.
CONTAINER_CMDS ?= podman docker
# QEMU package per host arch (for build-image-qemu, no script in image)
UNAME_M       := $(shell uname -m)
QEMU_PKG      := $(if $(filter aarch64 arm64,$(UNAME_M)),qemu-system-aarch64,qemu-system-x86)

.make-build-image-base: Dockerfile .make-dist
	@WHEEL="$$(find dist -maxdepth 1 -name '*.whl' -print -quit)"; \
	if [ -z "$$WHEEL" ]; then echo "No wheel in dist/"; exit 1; fi; \
	for CONTAINER_CMD in $(CONTAINER_CMDS); do \
	  if ! command -v $$CONTAINER_CMD >/dev/null 2>&1; then continue; fi; \
	  echo "Building python-sb:$(PYTHON_VERSION), python-sb:latest with $$CONTAINER_CMD (base)..."; \
	  $$CONTAINER_CMD build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  	--build-arg WHEEL="$$(basename $$WHEEL)" \
	  	-t python-sb:$(PYTHON_VERSION) \
	  	-t python-sb:subprocess \
	  	-t python-sb:landlock \
	  	-t python-sb:latest \
	  	-f Dockerfile . || exit 1; \
	done; \
	touch .make-build-image-base

.make-build-image-landlock: .make-build-image-base Dockerfile-landlock
	@for CONTAINER_CMD in $(CONTAINER_CMDS); do \
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
	@for CONTAINER_CMD in $(CONTAINER_CMDS); do \
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
	@for CONTAINER_CMD in $(CONTAINER_CMDS); do \
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
	@for CONTAINER_CMD in $(CONTAINER_CMDS); do \
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

## Build all provider images (and base first); see dependency graph above (for minikube: make minikube-build-images)
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
# The local full check before a final version. The CI publishes: nothing is uploaded from this machine.
.PHONY: release
## Run the full local check (validate and all-tests) before a final version
release: validate all-tests

uv.lock: pyproject.toml
	uv lock
	unset VIRTUAL_ENV && uv sync $(UV_GROUP)


## Refresh lock
lock: uv.lock

# format is not a prerequisite: it rewrites the sources, which would make the
# `black --check` inside lint pass unconditionally.
## Validate the code
validate: uv.lock lint spell_check pip-audit-all pip-audit unit-tests quick-demo-gif

# quick-demo.gif is recorded from these files. A change to their content records it again: a hash, kept in
# git, is compared rather than the dates, which a clone or a pull resets.
QUICK_DEMO := samples/quick-demo
QUICK_DEMO_INPUTS := $(addprefix $(QUICK_DEMO)/,gif-demo/demo.sh gif-demo/Makefile app/demo.py init.sh data/hello.txt)
QUICK_DEMO_HASH := $(QUICK_DEMO)/gif-demo/quick-demo.gif.sha256

## Record the quick demo GIF again if what produces it changed
quick-demo-gif:
	@hash=$$(cat $(QUICK_DEMO_INPUTS) | sha256sum | cut -d' ' -f1); \
	if [[ $$hash != "$$(cat $(QUICK_DEMO_HASH) 2>/dev/null)" ]]; then \
		$(MAKE) -C $(QUICK_DEMO)/gif-demo && echo "$$hash" >$(QUICK_DEMO_HASH); \
	fi


## Start MCP inspector
inspector:
	npx @modelcontextprotocol/inspector

github-push-test:
	gh act push

## Detect the system, install what it lacks (asks first), sync the environments, then report what is missing
init:
	@UV_GROUP="$(UV_GROUP)" scripts/setup/init.sh

## Report the tools and kernel settings a contributor needs, and what each missing one costs (changes nothing)
doctor:
	@scripts/setup/doctor.sh

## Install the system packages, uv and the AppArmor setting of a Linux or WSL2 workstation (asks first)
setup-linux:
	@scripts/setup/setup-linux.sh

## Install the command line tools, Homebrew packages and uv of a Mac (asks first)
setup-macos:
	@scripts/setup/setup-macos.sh

## Install uv, git and make on native Windows with winget (asks first); WSL2 is recommended
setup-windows:
	@scripts/setup/setup-windows.sh

## Build and provision the local Intel macOS VM with OSX-KVM, after an explicit licence validation (Linux, KVM)
init-macos-vm:
	@scripts/macos-vm/init.sh



### DEBUG ###

.PHONY: publish-pre-release publish-patch publish-minor publish-final

# Tags the head of develop with a signed vX.Y.Z(a|b|rc)N and pushes develop, then the tag: release.yml verifies it,
# builds the wheel and, once the testpypi deployment is approved, publishes it to test.pypi.org. The tag is signed
# on this machine only; review what the head brings before confirming, a published tag is never moved.
## Tag and push a pre-release, which the CI publishes to test.pypi.org: make publish-pre-release VERSION=0.1.0b2
publish-pre-release: quick-demo-gif
	@scripts/tag-release.sh pre "$(VERSION)"

# Final versions: the last final tag bumped, the CHANGELOG entry dated, a signed tag pushed after develop;
# release.yml publishes it to pypi.org once the pypi deployment is approved.
## Run the full local check, then tag and push the next patch version
publish-patch: quick-demo-gif
	$(MAKE) release
	@scripts/tag-release.sh patch

## Run the full local check and the samples on every Python and provider, then tag and push the next minor version
publish-minor: quick-demo-gif
	$(MAKE) release
	$(MAKE) sample-tests-matrix
	@scripts/tag-release.sh minor

## Run the full local check and the samples on every Python and provider, then tag and push a given final version: make publish-final VERSION=0.5.0
publish-final: quick-demo-gif
	$(MAKE) release
	$(MAKE) sample-tests-matrix
	@scripts/tag-release.sh final "$(VERSION)"
