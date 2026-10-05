# Registration points of an OS provider

Identifiers are named rather than line numbers. To list the current points, grep how the most recent provider is registered:

```bash
git ls-files | rg -v '^samples/|^research/' | xargs rg -l -i landlock | rg -v landlock
```

Every hit outside landlock's own modules is a place the new provider must appear (or be explicitly left out).

## Code

| File | Identifier | Change |
|------|-----------|--------|
| `pysandboxes/_os_sandbox.py` | `_PROVIDER_SPECS` | Add `"<name>": ("remote.<name>_daemon", "<Class>", <platforms>)`. For a new OS, add a frozenset next to `_LINUX` / `_ANY_OS` (`sys.platform` values: `darwin`, `win32`, ...). |
| `pysandboxes/remote/<name>_daemon.py` | provider class | New module. Import platform-only modules lazily or guard them. |
| `pysandboxes/remote/main_sandbox.py` | `assert os_sandbox in (...)` | Add the name to the tuple. |
| `pysandboxes/templates/<name>.template` | | Launcher providers only, if the command is built from a template. |
| `pysandboxes/__init__.py` | module docstring | Add the name to the provider list. |
| `pyproject.toml` | `[project.optional-dependencies]` | Add `<name> = [...]` and add it to `all`. Run `uv lock`. |

## Tests

| File | Identifier | Change |
|------|-----------|--------|
| `tests/integration_tests/_env.py` | `ALL_OS_SANDBOX` | Add the row. `os_sandbox_params()` drops rows not tagged for the running platform. |
| `tests/integration_tests/_env.py` | `provider_skip_reason()` | Only test-environment quirks (container, missing privilege). |
| `tests/unit_tests/test_provider_platforms.py` | expected `platform_providers()` lists | Update the list of every platform the provider is tagged for. |
| `tests/conftest.py` | `_LINUX_ONLY_TESTS` | Linux provider: add its modules. Other OS: extend the same pattern (a list excluded from collection when `sys.platform` differs). |
| `tests/integration_tests/tst_usage.py` | `.env` readability check | If the provider cannot hide a path (`ignore=`), add it next to `none` / `landlock`. |
| `tests/containers_tests/test_containers.py` | `all_os_sandbox_provider`, `needs_privileged` | Linux provider runnable in a container only. |
| `tests/integration_tests/remote/test_<name>.py`, `tests/unit_tests/remote/test_<name>_*.py` | | New suites. |

## CI and build

| File | Change |
|------|--------|
| `.github/workflows/cross-os.yml` | Non-Linux provider: the provider suites already run on `macos-latest` / `windows-latest` with `PYSANDBOXES_FAIL_ON_SKIP=1`; install the provider's prerequisites in that job. Add a matrix entry for a new OS. |
| `.github/workflows/integration.yml`, `containers.yml` | Linux provider: install its prerequisites on the runner. |
| `Dockerfile-<name>`, `Makefile` (`build-image-<name>`, `.make-build-image-<name>`, `IMAGE_STAMPS`, `MINIKUBE_IMAGES`, `build-images`) | Linux provider runnable in a container only, on the model of `Dockerfile-landlock`. |

## Documentation

| File | Change |
|------|--------|
| `wiki/<name>.md` | New page: how it works, prerequisites, limitations, running it. |
| `wiki/os-providers.md` | Provider table, guard column (✅/❌ per rule kind), deployment matrix rows. |
| `wiki/Home.md` | Link to the page. |
| `wiki/tests.md` | Provider rows of the test tables. |
| `wiki/implementation.md` | How the provider isolates. |
| `README.md` | Provider list; the "Linux WSL only" statement once another OS is supported. |
| `AGENTS.md`, `AGENTS.template.md` | Provider list. |
| `CONTRIBUTING.md` | List of per-provider wiki pages. |
| `SECURITY.md` | Provider list. |
| `CHANGELOG.md` | Entry, and the platform/provider table at the top. |
| `wiki/roadmap.md` | Mark the provider or platform as done. |
| `wiki/alternatives.md`, `wiki/use-cases.md` | Provider comparisons and use cases, if the provider changes them. |
| `wiki/audit-python-security.md` | What the provider holds against compiled code. |
| `coding-agents/README.md` | Provider list given to `python-sb` users. |

This table is the starting point of the question the skill asks the user (workflow step 7), not a substitute for it.

## Linux-only assumptions to avoid in a non-Linux provider

- `fcntl`, `os.fork`, `os.mkfifo` and named pipes, `/proc`, POSIX signals, uid/gid.
- Hard-coded paths (`/bin`, `/usr`, `/lib`, `/etc`, `/dev`, as in `_collect_landlock_paths`): derive the interpreter paths from `sys.executable`, `sys.path`, `site.getsitepackages()`.
- `slirp4netns` / iptables networking (`remote/slirp4netns_common.py`).
- Path separators and drive letters in rules and in tests.

## Verification

```bash
uv run pytest tests/unit_tests/test_provider_platforms.py
uv run pytest -rs tests/unit_tests/remote -k <name>
PYSANDBOXES_FAIL_ON_SKIP=1 uv run pytest -rs \
    tests/integration_tests/test_guards_with_providers.py \
    tests/integration_tests/test_usage_with_providers.py \
    tests/integration_tests/remote/test_<name>.py
# When the provider enforces net= at the OS level, with <name> in its _PROVIDERS:
PYSANDBOXES_FAIL_ON_SKIP=1 uv run pytest -rs tests/integration_tests/test_os_netfilter.py -k <name>
```

On a non-Linux target, run `.github/workflows/cross-os.yml` (manual dispatch) and require it green.
