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

"Parametrized" is not "verified": the QEMU rows of the second scenario have
never passed on a host without `/dev/kvm`, for a reason nobody has pinned down.
Five backends are green.

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

`make all-tests` (alias `make test`) chains all four.

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

**`test_guards_with_providers.py`** covers the other three families, six rows
per backend. Each family is a deny/allow pair: `eval('40 + 2')` refused, then
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

Five backends were verified when that file landed — `subprocess`, `unshare`,
`firejail`, `landlock`, `bwrap`: 30 of its 36 rows pass. The six QEMU rows were
not; see [Gaps](#gaps).

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
| `qemu` | yes | **unverified** | yes | yes | yes |

"Host: guards" is `test_guards_with_providers`.

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

The same convention applies on the host: `qemu` in partial mode is
`xfail(run=False)` in `test_usage_with_providers.py`, because the VM boot
exceeds the 30 s configuration timeout and the row would cost ten minutes to
fail. Five of the six partial-mode rows actually run.

Kubernetes rows need minikube and the per-backend images
(`make minikube-ready`, `make minikube-build-images`); they skip otherwise.

## Gaps

- **No container row arms `guard_eval`, `guard_api` or `guard_import`.** The
  container grid runs `tst_usage`, which exercises none of the three, under the
  shared profile, whose `python-import=*` disarms the import guard outright.
  Closing this means either teaching `tst_usage` those three families — and
  narrowing `python-import=` in a profile that feeds every container row — or
  giving the container suite a second scenario.
- **The six QEMU rows of `test_guards_with_providers` are unverified.** On a
  host with no `/dev/kvm` they exit 1 with an empty stderr, before any guard
  runs. The same profile and script pass on the other five backends, so this
  looks like the VM failing to come up rather than the guard — but the cause was
  not established, and it is untriaged, not expected. The silent exit is its own
  small problem: a user gets no diagnostic at all.
- **Split (partial) mode is untested in containers** — `test_containers.py`
  carries an explicit `# TODO: test with split mode`. It is covered on the host
  by `test_partial_mode_hides_the_parent_environment`.
- **Twelve unprivileged `unshare`/`bwrap` container rows never run.**
- `call_llm()` in `tst_usage.py` is defined but never invoked — dead code, not a
  provider test.
