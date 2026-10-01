# Test coverage map — what is exercised, where

This page answers one question: **are the guard families covered by integration
tests, for every `OS_SANDBOX` technology and in every container condition?**

The short answer is **per backend, yes; per container condition, no**.

Six families are now parametrized over every OS backend, by two scenarios.
`guard_files`, `guard_socket` and `guard_envs` ride on `tst_usage`, which is
also what every container row runs. `guard_eval`, `guard_api` and
`guard_import` are covered by `test_guards_with_providers`, which runs on the
host only — so no container row arms them. The seventh family,
`guard_provider`, parses configuration rather than guarding a call.

QEMU is run twice on the host: the `qemu` row takes KVM when `/dev/kvm` is
there, and the `qemu-tcg` row refuses it, so emulation is covered even on a
machine that has KVM.

The container grid is therefore narrower than the host one, and narrower still
than its row count suggests: a quarter of its rows are declared `xfail` and
never execute. See [Gaps](#gaps).

Everything below is derived from the test sources, not from intent:
`tests/unit_tests/`, `tests/integration_tests/`, `tests/containers_tests/`.

## The four suites

| Suite | Make target | What it runs |
|---|---|---|
| Unit | `make unit-tests` | `tests/unit_tests/` — guards called directly, in-process, no daemon |
| Integration | `make integration-tests` | `tests/integration_tests/` — a real `python-sb` child process per backend |
| Containers | `make container-tests` | `tests/containers_tests/` — Docker, Podman, Kubernetes (minikube) |
| Samples | `make sample-tests` | each sample's own test suite |

`make all-tests` chains all four.

## Orders of magnitude

How many tests that represents, in collected rows rather than in the coverage
cells of [section D](#d-counting-the-scenarios). The figures move with every
commit that adds a test; the point is the shape of the effort:

| Suite | Target | Tests |
|---|---|---|
| Unit | `make unit-tests` | ~1410 |
| Integration | `make integration-tests` | ~135 |
| Containers | `make container-tests` | ~60 |
| Samples (12 demos) | `make sample-tests` | ~170 |
| **Total, one interpreter** | `make all-tests` | **~1775** |

The samples figure is the softest of the four: each sample has its own
`pyproject.toml`, its own lock file and its own virtual environment, so the
suites can only be collected once those environments exist.

Not every suite is replayed on every interpreter, and no single event runs all
of it:

| Workflow | Suite | Versions | Executions | Fires on |
|---|---|---|---|---|
| `test.yml` | Unit | 3.11, 3.12, 3.13, 3.14 | ~5640 | every push and pull request |
| `integration.yml` | Integration | 3.11, 3.12, 3.13, 3.14 | ~540 | `full-gate.yml` (nightly 20:17 UTC, release tag) or dispatch |
| `containers.yml` | Containers | 3.13 | ~60 | `full-gate.yml` (nightly 20:17 UTC, release tag) or dispatch |
| `samples.yml` | Samples | 3.11, 3.12, 3.13, 3.14 | ~650 | `full-gate.yml` (nightly 20:17 UTC, release tag) or dispatch |
| **Total** | | | **~6890** | |

The samples row is not a clean multiplication: a sample whose `requires-python`
excludes the matrix interpreter is *skipped*, not failed. `langgraph-demo` is
3.13+, so its suite runs on two rows of four — the Makefile compares the two
versions with `sort -V` and prints a `skip` line rather than trying to resolve
the environment. `full-gate.yml`, which holds the schedule, opens with the guard
job that exits early when the branch has not changed since the last run; the suites
it calls have none of their own.

## A. Guard families

| Family | Module | Unit | Integration (host) | Containers |
|---|---|---|---|---|
| Filesystem | `guard_files` | yes | all 6 backends | all conditions |
| Network | `guard_socket` | yes | all 6 backends | all conditions |
| Environment | `guard_envs` | yes | all 6 backends | all conditions |
| Dynamic code | `guard_eval` | yes (largest unit block) | all 6 backends + depth on `subprocess` | **no** |
| Sensitive API | `guard_api` | yes | all 6 backends + arming on `subprocess` | **no** |
| Imports | `guard_import` | yes | all 6 backends | **no** |
| Config directives | `guard_provider` | yes | indirect (every profile load) | indirect |

Two scenarios carry the per-backend column, and they are shaped differently.

**`tst_usage.py`** covers files, sockets and environment variables. It is
invoked once per backend by `test_usage_with_providers.py` and once per
container row by `test_containers.py` — which is why those three families, and
only those three, reach the container grid. It asserts a write inside
`expose-rw` succeeding while a write outside it is denied and `.env` stays
unreadable; TCP/UDP connect, bind and DNS following the `net=` rules; and the
sandbox seeing no variable outside a known allowlist, in particular neither
`USER` nor the planted `USAGE_SECRET`.

One qualification on that envs check: the allowlist (`_EXPECTED_ENVS`) is wider
than the profile's two `env=` rules. It also accepts the per-technology plumbing
each backend re-exports (`PATH`, `PYTHONPATH`, `COLUMNS`, `PYTHONUNBUFFERED`…),
and it grows deliberately as backends add exports. The check catches an
*unknown* name, not every name.

**`test_guards_with_providers.py`** covers the other three families, six tests
per backend row. Each family is a deny/allow pair: `eval('40 + 2')` refused, then
allowed by `python-api=ALLOW:dynamic-code`; `os.system` refused, then allowed by
`python-api=ALLOW:os.system`; an unlisted module refused by name, then accepted
once `python-import=` names it. The pairing is the point — a deny row alone
cannot distinguish a working guard from an interpreter that never started, since
both exit non-zero.

It writes its profile per test rather than using the shared one, for two
reasons. `py-sandbox-test.profile` carries `net=` rules whose hostnames must
resolve at config load, which would skip the whole file on a host without DNS
for a reason unrelated to arming; and it carries `python-import=*`, which
disarms the very guard under test. The profile exposes the interpreter's own
library tree explicitly, since a backend with its own mount namespace otherwise
hides it.

Four more tests per row cover what the guards rest on: the program's output
comes back, a profile naming its modules one by one still starts, a failure
says why, and stdout and stderr stay apart. The first three pin the defects
that made every QEMU row exit 1 with an empty stderr; with them fixed, the QEMU
rows run like the others. Ten tests over seven rows: 70 rows.

`test_eval_integration.py` and `test_guard_api_arming.py` stay pinned to
`os-sandbox=subprocess`, and keep their role: depth rather than breadth. They
cover the eval sub-language (namespaces, syntax classes, timeouts, the learning
round trip) and each of the arming entry points — work that does not need to be
repeated per backend once arming itself is shown to survive one.

`guard_provider` parses the configuration directives (`os-sandbox=`,
`py-sandbox=`, `port=`, `learn=`); it is not a runtime guard, and every test
that loads a profile exercises it implicitly.

## B. OS_SANDBOX backends

Nine providers are registered in `pysandboxes/_os_sandbox.py`; `_task` and
`_sse_server` are internal and not user-selectable.

| Backend | Host: `tst_usage` | Host: guards | Docker | Podman | Kubernetes |
|---|---|---|---|---|---|
| `subprocess` | yes | yes | — | — | — |
| `firejail` | yes | yes | **excluded** | **excluded** | **excluded** |
| `bwrap` | yes | yes | yes (privileged) | yes (privileged) | yes (privileged) |
| `unshare` | yes | yes | yes (privileged) | yes (privileged) | yes (privileged) |
| `landlock` | yes | yes | yes | yes | yes |
| `qemu` | yes | yes | yes | yes | yes |
| `qemu-tcg` | yes | yes | — | — | — |

"Host: guards" is `test_guards_with_providers`. `qemu-tcg` is not a backend but
a second host row for `qemu` with `qemu.use_kvm=false` (`ALL_OS_SANDBOX` in
`tests/integration_tests/_env.py`). It carries the `slow` marker, which is how a
release run leaves it out (`exclude-tcg` in `integration.yml`); the nightly runs it.

`none` is left out of this page. It is the no-op provider — a development aid,
not a confinement technology — so nothing it does or fails to do says anything
about the guards. The container grid still parametrizes it, which is where the
twelve `none` rows in the counts below come from; they are not coverage of
anything and are excluded from every figure that follows.

The two lists are deliberately disjoint at the edges. `firejail` is incompatible
with containers and is excluded from the container matrix outright. `subprocess`
is the fallback of the test profile (`os-sandbox=${OS_SANDBOX:-subprocess}`) and
is not re-tested in containers, where the container already provides what it
does not. Note that `make container-tests` defaults to `unshare`, not
`subprocess` — but that variable only selects the image; the test grid
parametrizes every backend regardless.

Every host row skips itself when its binary or kernel feature is missing
(`firejail`, `bwrap`, `slirp4netns`, Landlock ≥ 5.13, `qemu-system-*`), so the
suite stays portable; a skip is not a pass.

Each backend is also covered by a small liveness test under
`tests/integration_tests/remote/` (`test_bwrap.py`, `test_firejail.py`,
`test_landlock.py`, `test_unshare.py`) that only checks a sync and an async
`@sandbox` call round-trip — not the guards.

## C. Container conditions

`test_containers.py` parametrizes the full grid: `py_sandbox` {true, false} ×
`privileged` {true, false} per backend, over Docker, Podman and Kubernetes. Each
row runs the same `tst_usage.py` scenario. Counting only the four real backends
(`none` aside), that is 48 rows.

`py_sandbox=false` is what makes the grid worth running: it removes the Python
layer and leaves the container plus the OS backend alone, which is how a row
proves the OS layer denies on its own rather than riding on the patched
interpreter.

| Condition | Rows | Status |
|---|---|---|
| `landlock`, `qemu` — privileged and unprivileged | 24 | run |
| `unshare`, `bwrap` — privileged | 12 | run |
| `unshare`, `bwrap` — **unprivileged** | 12 | **`xfail(run=False)`** |

The last line matters: those twelve rows are *declared*, not executed. Both
backends build their own namespaces and mounts, which an unprivileged container
does not grant, so the row is marked rather than silently dropped — but it is
not coverage. A quarter of the container grid is a label.

The host no longer has any: `qemu` in partial mode used to be `xfail`, and
every partial-mode row of `test_usage_with_providers.py` now runs
(`_PARTIAL_MODE_XFAIL` is empty).

Kubernetes rows need minikube and the per-backend images
(`make minikube-ready`, `make minikube-build-images`); they skip otherwise.

## D. Counting the scenarios

A single product over every axis would be wrong twice over: one row of
`tst_usage` arms three families at once, and a `py_sandbox=false` row cannot arm
the three Python-level families at all. The count is therefore a sum over
conditions, expressed in *cells* — one cell is a (Python version, backend, guard
family, condition) tuple — rather than in pytest rows.

| Symbol | Meaning | Value | Source |
|---|---|---|---|
| `V_host` | Python versions the host grid runs | 4 | the `integration.yml` matrix, `3.11` to `3.14`, matching `requires-python = ">=3.11,<3.15"` |
| `V_ctn` | Python versions the container grid runs | 1 | `_image_name()` returns `:latest`; `ARG PYTHON_VERSION` is a build knob, not a test axis |
| `P_host` | backends on the host | 6 | `ALL_OS_SANDBOX` in `tests/integration_tests/_env.py`, `qemu-tcg` counted with `qemu` |
| `P_ctn` | backends in containers, `none` excluded | 4 | `all_os_sandbox_provider` minus `none` |
| `G` | armable guard families | 6 | section A; `guard_provider` is excluded — it parses configuration, it does not guard a call |
| `G_os` | families still enforced without the Python layer | 3 | files, socket, envs — empirically, the 24 `py_sandbox=false` container rows run `tst_usage` and pass, which is what makes those three OS-enforced rather than guard-enforced |
| `M` | host modes | 2 | complete, partial (`test_partial_mode_hides_the_parent_environment`) |
| `R` | container runtimes | 3 | docker, podman, kubernetes |
| `K` | privilege conditions | 2 | `privileged` {true, false} |

**What full coverage would demand**

```
N_ideal = V_host x P_host x M x G                    (host)
        + V_ctn  x P_ctn  x R x K x (G + G_os)       (containers)

        = 4 x 6 x 2 x 6   +   1 x 4 x 3 x 2 x (6 + 3)
        = 288 + 216
        = 504
```

The `(G + G_os)` term is the `py_sandbox` axis written honestly. The
`py_sandbox=true` half of the container grid can arm all six families; the
`py_sandbox=false` half removes the Python layer, so it can only arm the three
the OS enforces on its own. The 72 cells that difference removes are not a gap —
they are inapplicable, and counting them would inflate the denominator.

**What the suites cover**

```
N_covered = V_host x P_host x 3   (tst_usage on the host: files, socket, envs)    =  72
          + V_host x P_host x 3   (test_guards_with_providers: eval, api, import) =  72
          + V_host x P_host x 1   (partial mode: environment variables only)      =  24
          + 48 x 3       (every real-backend container row runs tst_usage)        = 144
          = 312
```

**What actually executes** — subtract the `xfail(run=False)` cells: the twelve
unprivileged `unshare`/`bwrap` container rows (12 x 3 = 36 cells).

```
N_run = 312 - 36 = 276
```

| | Cells | Of 504 |
|---|---|---|
| Declared | 312 | 62 % |
| Executed | 276 | 55 % |

Row counts, to cross-check against the sections above: 84 host rows per
interpreter and 60 container rows, 48 of them on a real backend. Both are reproducible with
`pytest --collect-only -q`. Unit tests sit outside this grid entirely — ~1410
collected, none parametrized by backend or container condition — so they scale
with the Python version alone.

Two facts fall out of the arithmetic that the tables above do not show. Partial
mode arms one family of six: the mode is parametrized over every backend, but
the only assertion is about environment variables. And `V_ctn` is 1 against a
`requires-python` that claims four interpreters: raising it means building and
tagging the per-version images, since the grid asks for `:latest`. That is not a
code change: the five `Dockerfile*` already take `ARG PYTHON_VERSION`, and the
Makefile derives it from the venv's interpreter. What holds it back is runtime — the container job is already budgeted at 300
minutes for a single version, most of it QEMU booting under emulation.

## Gaps

- **No container row arms `guard_eval`, `guard_api` or `guard_import`.** The
  container grid runs `tst_usage`, which exercises none of the three, under the
  shared profile, whose `python-import=*` disarms the import guard outright.
  Closing this means either teaching `tst_usage` those three families — and
  narrowing `python-import=` in a profile that feeds every container row — or
  giving the container suite a second scenario.
- **Split (partial) mode is untested in containers** — `test_containers.py`
  carries an explicit `# TODO: test with split mode`. It is covered on the host
  by `test_partial_mode_hides_the_parent_environment`.
- **Twelve unprivileged `unshare`/`bwrap` container rows never run.**
- **Partial mode arms one guard family of six.** The mode is parametrized over
  every backend, but the only assertion is about environment variables — see
  section D.
- **The container grid runs one interpreter against a four-version support
  claim.** `requires-python = ">=3.11,<3.15"`, while `containers.yml` pins
  `3.13` and the grid asks for `:latest`. The unit, integration and sample
  suites cover the four — see section D.
- `call_llm()` in `tst_usage.py` is defined but never invoked — dead code, not a
  provider test.
