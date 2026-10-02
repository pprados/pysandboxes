# Contributing to PySandboxes

PySandboxes runs code its caller does not trust, so a contribution is judged first on whether the sandbox
still holds after it. This page says how to get started, how to propose a change, and what a pull request
must carry. It is also the checklist the automated review applies.

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security issues first

A vulnerability is never reported in an issue or a pull request, not even as a fix. Follow
[`SECURITY.md`](SECURITY.md): a private GitHub security advisory, or `github@prados.fr`. The same page lists what
does not count as a vulnerability, such as the known Python-layer weaknesses in
[`wiki/weaknesses.md`](wiki/weaknesses.md); those are welcome as ordinary issues.

## Getting started

The project runs on Linux or WSL (every OS provider is a Linux technology), with Python 3.11 to 3.14, and uses
[uv](https://docs.astral.sh/uv/) exclusively.

```bash
git clone https://github.com/pprados/pysandboxes.git
cd pysandboxes
git checkout develop
make init        # uv sync --group dev --group test --group lint, plus the gh act extension
```

A plain `uv sync` installs the `dev` group only and removes the linters. `make help` lists every target.

### Where things are

| Path | What it holds |
|---|---|
| `pysandboxes/sandboxes_api.py` | the public API: `@sandbox` and the `sandboxes()` context manager |
| `pysandboxes/py_sandbox.py` | the Python layer, which patches the standard library at run time |
| `pysandboxes/_os_sandbox.py` | the registry of OS providers, from `none` to `qemu` |
| `pysandboxes/guard_*.py` | one guard per resource: files, network, imports, env, sensitive calls, eval |
| `pysandboxes/eval_*.py` | the `eval-*` sub-language: rules, AST rewriting, runtime checks |
| `pysandboxes/remote/` | the SSE channel between the host and the sandboxed child |
| `tests/unit_tests/`, `tests/integration_tests/` | the two suites that gate a pull request |
| `samples/` | self-contained demos, each with its own `uv` environment and `Makefile` |
| `wiki/` | design notes, one page per provider, known weaknesses, test matrix (`wiki/tests.md`) |

### The wiki

The [`wiki/`](wiki/Home.md) directory holds the documentation a contributor needs before touching the code:

- [`implementation.md`](wiki/implementation.md): how the framework is put together;
- [`weaknesses.md`](wiki/weaknesses.md) and the two security assessments: what the Python layer does not stop,
  and the attacks already studied;
- one page per OS provider (`bwrap.md`, `firejail.md`, `unshare.md`, `qemu.md`, `landlock.md`), and
  [`eval.md`](wiki/eval.md) for the `eval-*` rules;
- [`tests.md`](wiki/tests.md): which suite covers what, and the gaps;
- [`release.md`](wiki/release.md): how a pre-release is published, and the settings behind it;
- [`roadmap.md`](wiki/roadmap.md) and [`faq.md`](wiki/faq.md): where the project is going, and common
  questions.

Read the page of the component you change first: a change that contradicts it updates it in the same pull
request.

### The security model

In one sentence: everything is denied by default, and a `.py-sandboxes` rule file grants
what a program needs, enforced twice, by the Python layer and by the OS provider.

## Branches

- **`develop`** is the integration branch. Branch from it, and open every pull request against it.
- **`master`** only receives releases, merged by a maintainer. A pull request towards `master` is not accepted.

## Before opening a pull request

```bash
make format
make validate          # lock, lint, spell check, dependency audit, unit tests
make integration-tests # when the change touches a provider, the remote layer or a full workflow
```

`.github/prompts/pre-pr-quality-check.prompt.md` gives the same steps to a coding agent.

## Pull request requirements

### Scope

- One purpose per pull request. Every changed line traces to it; no refactoring of code the change does not
  need.
- Commit subjects follow Conventional Commits: `fix(guard): ...`, `test(integration): ...`, `docs: ...`.

### Code

- Type hints on all code, Python 3.11 syntax (`str | None`, not `Optional[str]`).
- Docstrings on public APIs. Small, focused functions that follow the pattern of their neighbours (a new guard
  follows the `guard_*.py` pattern).
- Lines of at most 120 characters, formatted by `black`.
- Dependencies through `uv` only; refresh `uv.lock` (`make lock`) when `pyproject.toml` changes.
- Every new Python file starts with:

  ```python
  # Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
  # License: Apache V2
  ```

### Security model

- Default deny stays: no default, fallback or rule that widens what sandboxed code may do.
- A change to a guard, to `eval_*`, to a provider or to rule parsing says which layer it touches (Python or
  OS) and comes with a test proving the refusal still holds.
- Nothing may let sandboxed code widen its own permissions: rule files, learning-mode output, configuration
  paths.
- A new sensitive function is registered in `guard_api` under one of its categories.

### Tests

A test for a guard must be able to fail. The rules below come from bugs that shipped because a test could not:

- Never disarm the sandbox under test: `OS_SANDBOX=none`, in a conftest, an env file or a Makefile target,
  disarms the Python guards too, and the suite can no longer fail.
- Give every blocking assertion a negative control proving the operation succeeds without the sandbox, run in
  its own process: a block earlier in the same process short-circuits the next one.
- Assert a refusal through `sandbox_denials()`, not through an error message: libraries rewrite a blocked
  connection into wording any outage produces.
- Keep `pytest.raises` narrow. A `NameError`, `TypeError` or `AttributeError` proves the payload broke, not
  that a rule refused it.
- An escape test never builds a real `Popen` whose success would do harm; aim it at a harmless target.
- Assert the return value of the API under test, and make sure every profile a test names exists on disk:
  a missing profile silently switches to learning mode, where nothing is denied.

### Workflows

- No `ref:` under `actions/checkout`: it disables the local run through `act` (`make gh-tests`). Pin a branch
  through a `run:` step guarded by `if: github.event_name == ...`.
- A `schedule:` workflow pins or asserts the branch it tests, and never re-fetches a later commit than its own.
- Minimal `permissions:`, and no secret reachable by code coming from a fork.

### Documentation

- A user-visible change updates `README.md`, the `wiki/` page concerned, or `CHANGELOG.md`.
- A new known weakness goes into `wiki/weaknesses.md`, not under the carpet.

## Review

CI runs lint and unit tests on every pull request. A maintainer may also ask for an automated review by
adding the `claude-review` label. That review:

- applies the requirements above, read from a copy of `develop` taken before the review starts, so a pull
  request cannot change the criteria it is reviewed against;
- reads the pull request only through its diff, and refuses to review a head that moved after the label was
  set: relabel to review new commits;
- only posts comments: it never runs the pull request's code, never pushes, never approves.

The decision to merge always stays with a maintainer.

## License

Contributions are accepted under the [Apache License 2.0](LICENSE.txt), the license of the project.
