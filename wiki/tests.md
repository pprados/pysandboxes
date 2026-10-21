# Test coverage map — what is exercised, where

This page maps test evidence across guard families, OS providers, and container
conditions. A provider row means that a scenario is configured for that provider;
it does not mean the row ran successfully on every host.

## At a glance

- The host integration suite exercises six runtime guard families over six
  distinct OS providers. QEMU has two rows: KVM and forced TCG emulation.
- Container scenarios exercise file, socket, and environment behavior. They do
  not exercise `guard_eval`, `guard_api`, or `guard_import`.
- `unshare` and `bwrap` are not run with `--privileged` in the unprivileged rows: they get reduced privileges, and
  all twelve rows run, on Docker, Podman and Kubernetes (see [Container conditions](#c-container-conditions)).
- Test counts below are approximate collected-case counts. Provider availability,
  workflow filters, and sample environments change how many cases actually run.

See [Gaps](#gaps) for behaviors not represented by these matrices.

## Contents

- [Test suites and approximate size](#the-four-suites)
- [Guard family coverage](#a-guard-families)
- [Provider matrix](#b-os_sandbox-backends)
- [Container conditions](#c-container-conditions)
- [Synthesis of the validated scenarios](#d-synthesis-of-the-validated-scenarios)
- [Gaps](#gaps)

The tables are derived from [unit tests](../tests/unit_tests/),
[integration tests](../tests/integration_tests/),
[container tests](../tests/containers_tests/), and the corresponding CI
workflows. See [test workflow](../.github/workflows/test.yml),
[integration workflow](../.github/workflows/integration.yml),
[container workflow](../.github/workflows/containers.yml), and
[full-gate workflow](../.github/workflows/full-gate.yml).

## The four suites

| Suite | Make target | What it runs |
|---|---|---|
| Unit | `make unit-tests` | [`tests/unit_tests/`](../tests/unit_tests/) — guards called directly, in-process, no daemon |
| Integration | `make integration-tests` | [`tests/integration_tests/`](../tests/integration_tests/) — real `python-sb` child processes |
| Containers | `make container-tests` | [`tests/containers_tests/`](../tests/containers_tests/) — Docker, Podman, Kubernetes (minikube) |
| Samples | `make sample-tests` | each sample's own test suite |

`make all-tests` chains all four.

## Orders of magnitude

How many tests that represents, in collected rows. The per-scenario view is
[section D](#d-synthesis-of-the-validated-scenarios). The figures are approximate; the point is
the shape of the effort:

| Suite | Target | Tests |
|---|---|---|
| Unit | `make unit-tests` | ~3790 |
| Integration | `make integration-tests` | ~330 |
| Containers | `make container-tests` | ~60 |
| Samples (12 demos) | `make sample-tests` | ~230 |
| **Total, one interpreter** | `make all-tests` | **~4410** |

The samples figure is the softest of the four: each sample has its own
`pyproject.toml`, its own lock file and its own virtual environment, so the
suites can only be collected once those environments exist.

Not every suite is replayed on every interpreter, and no single event runs all
of it:

| Workflow | Suite | Versions | Executions | Fires on |
|---|---|---|---|---|
| [`test.yml`](../.github/workflows/test.yml) | Unit | 3.11, 3.12, 3.13, 3.14 | ~15160 | every push and pull request |
| [`integration.yml`](../.github/workflows/integration.yml) | Integration | 3.11, 3.12, 3.13, 3.14 | ~1310 | `full-gate.yml` (nightly, release tag) or dispatch |
| [`containers.yml`](../.github/workflows/containers.yml) | Containers | 3.13 | ~60 | `full-gate.yml` (nightly, release tag) or dispatch |
| [`samples.yml`](../.github/workflows/samples.yml) | Samples | 3.11, 3.12, 3.13, 3.14 × subprocess, landlock, bwrap, firejail, unshare | ~4460 | `full-gate.yml` (nightly, release tag) or dispatch |
| **Total** | | | **~20990** | |

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
| Filesystem | `guard_files` | yes | all 6 providers | all container rows |
| Network | `guard_socket` | yes | all 6 providers | all container rows |
| Environment | `guard_envs` | yes | all 6 providers | all container rows |
| Dynamic code | `guard_eval` | yes (largest unit block) | all 6 providers + depth on `subprocess` | **no** |
| Sensitive API | `guard_api` | yes | all 6 providers + arming on `subprocess` | **no** |
| Imports | `guard_import` | yes | all 6 providers | **no** |
| Config directives | `guard_provider` | yes | indirect (every profile load) | indirect |

Two scenarios carry the per-backend column, and they are shaped differently.

**[`tst_usage.py`](../tests/integration_tests/tst_usage.py)** covers files,
sockets and environment variables. It is invoked once per provider row by
[`test_usage_with_providers.py`](../tests/integration_tests/test_usage_with_providers.py)
and once per container row by
[`test_containers.py`](../tests/containers_tests/test_containers.py) — which is why those three families, and
only those three, reach the container grid. It asserts three things. A write
inside `expose-rw` succeeds, while a write outside it is denied and `.env` stays
unreadable. TCP/UDP connect, bind and DNS follow the `net=` rules. The sandbox
sees no variable outside a known allowlist, in particular neither `USER` nor the
planted `USAGE_SECRET`.

One qualification on that envs check: the allowlist (`_EXPECTED_ENVS`) is wider
than the profile's two `env=` rules. It also accepts the per-technology plumbing
each backend re-exports (`PATH`, `PYTHONPATH`, `COLUMNS`, `PYTHONUNBUFFERED`…),
and it grows deliberately as backends add exports. The check catches an
*unknown* name, not every name.

**[`test_guards_with_providers.py`](../tests/integration_tests/test_guards_with_providers.py)**
covers the other three families with a deny/allow pair per family: `eval('40 + 2')` refused, then
allowed by `python-api=ALLOW:dynamic-code`; `os.system` refused, then allowed by
`python-api=ALLOW:os.system`; an unlisted module refused by name, then accepted
once `python-import=` names it. The pairing is the point — a deny row alone
cannot distinguish a working guard from an interpreter that never started, since
both exit non-zero.

It writes its profile per test rather than using the shared one, for two
reasons. First, `py-sandbox-test.profile` carries `net=` rules whose hostnames
must resolve at config load: on a host without DNS, that would skip the whole
file for a reason unrelated to arming. Second, it carries `python-import=*`,
which disarms the very guard under test. The profile exposes the interpreter's own
library tree explicitly, since a backend with its own mount namespace otherwise
hides it.

Four more parametrized cases per row cover what the guards rest on: the program's output
comes back, a profile naming its modules one by one still starts, a failure
says why, and stdout and stderr stay apart. The first three pin the defects
that made every QEMU row exit 1 with an empty stderr; with them fixed, the QEMU
rows run like the others. The module has ten parametrized test functions across
seven provider rows (QEMU KVM and TCG are separate rows), or about 70 collected
cases before environment-dependent skips.

[`test_eval_integration.py`](../tests/integration_tests/test_eval_integration.py)
and [`test_guard_api_arming.py`](../tests/integration_tests/test_guard_api_arming.py)
stay pinned to
`os-sandbox=subprocess`, and keep their role: depth rather than breadth. They
cover the eval sub-language (namespaces, syntax classes, timeouts, the learning
round trip) and each of the arming entry points. That work does not need to be
repeated per backend once arming itself is shown to survive one.

`guard_provider` parses the configuration directives (`os-sandbox=`,
`py-sandbox=`, `port=`, `learn=`); it is not a runtime guard, and every test
that loads a profile exercises it implicitly.

## B. OS_SANDBOX backends

Nine entries are registered in `pysandboxes/_os_sandbox.py`: seven providers, plus
`_task` and `_sse_server`, which are internal and not user-selectable.

| Backend | Host: `tst_usage` | Host: guards | OS-only netfilter | Docker | Podman | Kubernetes |
|---|---|---|---|---|---|---|
| `subprocess` | yes | yes | — | — | — | — |
| `firejail` | yes | yes | yes (2 modes) | **excluded** | **excluded** | **excluded** |
| `bwrap` | yes | yes | yes (2 modes) | yes (privileged) | yes (privileged) | yes (privileged) |
| `unshare` | yes | yes | yes (2 modes) | yes (privileged) | yes (privileged) | yes (privileged) |
| `landlock` | yes | yes | yes (ABI v4) | yes | yes | yes |
| `qemu` | yes | yes | yes (KVM) | yes | yes | yes |
| `qemu-tcg` | yes | yes | — | — | — | — |

"Host: guards" is `test_guards_with_providers`. `qemu-tcg` is not a backend but
a second host row for `qemu` with `qemu.use_kvm=false` (`ALL_OS_SANDBOX` in
`tests/integration_tests/_env.py`). It carries the `slow` marker, which is how a
release run leaves it out (`exclude-tcg` in `integration.yml`); the nightly runs it.

`none` is left out of the provider table. It is the no-op provider — a
development aid, not a confinement technology — so nothing it does or fails to
do says anything about the guards. The container grid still parametrizes it,
which contributes twelve cases to the collected row count. Those cases are
excluded from the coverage-cell arithmetic because they do not test a boundary.

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
`tests/integration_tests/remote/test_providers.py`, one case per backend, that only checks a sync and an async
`@sandbox` call round-trip — not the guards.

The grid profile sets `bwrap.share-net=yes`, so its bwrap rows run on the host
network. The Python guards also refuse what the OS filter should, so a broken
filter leaves the grid green. The
[`test_os_netfilter.py`](../tests/integration_tests/test_os_netfilter.py)
scenario checks OS-only network enforcement with `py-sandbox=false` for
`bwrap`, `unshare`, `qemu`, and (when Landlock ABI v4 is available) `landlock`,
under both `python-sb` and daemon mode. It pairs a denied connection with a
permitted control connection. [`remote/test_bwrap.py`](../tests/integration_tests/remote/test_bwrap.py)
also exercises the bwrap daemon with the network-filtered profile.

`tst_usage.py` cannot prove the Firejail filter by itself because the Python
socket guard is also active. The OS-only scenario covers Firejail alongside
the other providers. Firejail supports
`--net=<bridge>` with an automatically assigned sandbox address and the bridge
address as its gateway; `--netfilter` applies only inside that new network
namespace ([Firejail manual](https://manpages.ubuntu.com/manpages/noble/man1/firejail.1.html)).
The integration workflow creates a private bridge, binds two listeners to its
gateway address, and checks that one TCP port is allowed while the other is
refused. This requires network administration capabilities and
`restricted-network no`; if Firejail is explicitly configured with
`restricted-network yes`, it keeps the host network and skips this OS filter.
Both denied and permitted connection controls are retained.

## C. Container conditions

`test_containers.py` parametrizes the full grid: `py_sandbox` {true, false} ×
`privileged` {true, false} per backend, over Docker, Podman and Kubernetes. Each
row runs the same `tst_usage.py` scenario. Counting only the four real backends
(`none` aside), that is 48 rows.

`py_sandbox=false` is what makes the grid worth running. It removes the Python
layer and leaves the container plus the OS backend alone. In effect, this is how
a row proves the OS layer denies on its own rather than riding on the patched
interpreter.

| Condition | Rows | Status |
|---|---|---|
| `landlock`, `qemu` — privileged and unprivileged | 24 | run |
| `unshare`, `bwrap` — privileged | 12 | run |
| `unshare`, `bwrap` — unprivileged, reduced privileges | 12 | run |

Both backends build their own namespaces and mounts, which the default container
confinement refuses. Neither needs `--privileged`: the unprivileged rows add the
least that worked, measured per engine with the real `tst_usage` scenario.

| Backend | Docker | Podman | Kubernetes pod |
|---|---|---|---|
| `bwrap` | `--cap-add SYS_ADMIN`, `seccomp=unconfined` and `apparmor=unconfined` (each is needed) | `--cap-add SYS_ADMIN` | `SYS_ADMIN`, `seccompProfile` and `appArmorProfile` `Unconfined` |
| `unshare`, with `UNSHARE_PROC=none` | `--cap-add NET_ADMIN --device /dev/net/tun --cap-add SYS_ADMIN --security-opt apparmor=unconfined` | `--cap-add NET_ADMIN --device /dev/net/tun` | `SYS_ADMIN` and `NET_ADMIN`, `seccompProfile` and `appArmorProfile` `Unconfined` |

Docker's default AppArmor profile and seccomp filter block what these providers
do; Podman's default confinement lets `CAP_SYS_ADMIN` through. The Kubernetes
column is the set the rows use, not a measured minimum.

`UNSHARE_PROC=none` sets `unshare.proc=none` in the test profile: `unshare` runs
without a `/proc`. Mounting a new `/proc` needs the masked paths unmasked
(`--security-opt systempaths=unconfined`, or `procMount: Unmasked`, which needs
`hostUsers: false`, and the minikube runtime refuses it). Without a `/proc`, the
file guard resolves a `dir_fd` from the path it recorded when `os.open` returned
the descriptor, instead of reading `/proc/self/fd/N`. `tst_usage` does not use
`dir_fd`; the unit tests of `test_guard_files_no_proc.py` and the `unshare`
integration test of `rmtree` cover it.

The host has none: every partial-mode row of `test_usage_with_providers.py`
runs (`_PARTIAL_MODE_XFAIL` is empty).

Kubernetes rows need minikube and the per-backend images
(`make minikube-ready`, `make minikube-build-images`); they skip otherwise.

## D. Synthesis of the validated scenarios

Where each scenario runs, by operating system. The kernel-backed providers are Linux
technology, so macOS and Windows run the Python layer over `subprocess`; the
[cross-os workflow](../.github/workflows/cross-os.yml) is what proves those two rows.

| Scenario | Linux | macOS | Windows | Interpreters |
|---|---|---|---|---|
| Unit | whole suite | whole suite, Linux-only modules skipped | whole suite, Linux-only modules skipped | 3.11 to 3.14 |
| Integration, per provider | `subprocess`, `firejail`, `bwrap`, `unshare`, `landlock`, `qemu` (KVM and TCG) | `subprocess` | `subprocess` | 3.11 to 3.14 |
| OS-only network filter | `bwrap`, `unshare`, `qemu`, `landlock` (ABI v4), `firejail` | — | — | 3.11 to 3.14 |
| Containers: Docker, Podman, Kubernetes | 48 rows on a real backend, 12 on `none` | — | — | 3.13 |
| Samples (12 demos) | every provider | `subprocess` | `subprocess` | 3.11 to 3.14 |

- **Guards.** Every integration row arms the six families described in
  [section A](#a-guard-families): `tst_usage` for files, sockets and environment,
  `test_guards_with_providers` for eval, API and imports. The container rows run
  `tst_usage` only, with and without the Python layer (`py_sandbox`), so they show
  that files, sockets and environment are enforced by the OS layer alone.
- **Providers in containers.** `landlock` and `qemu` run privileged and not.
  `unshare` and `bwrap` run privileged, and with the reduced privileges of
  [section C](#c-container-conditions). `firejail` is excluded.
- **Containers on macOS and Windows.** Not run: the providers under test need a
  Linux kernel, and Docker there runs a Linux VM, which adds nothing to the proof.
- **Samples.** `langgraph-demo` needs Python 3.13, so its suite is skipped on 3.11
  and 3.12 on every OS. On Linux, `make sample-tests-matrix` runs every sample
  on every interpreter and every provider.

Row counts, to cross-check against the sections above: 84 host rows per
interpreter and 60 container rows, 48 of them on a real backend. Both are
reproducible with `pytest --collect-only -q`. Unit tests sit outside these grids
entirely, with about 3790 collected and none parametrized by backend or
container condition, so they scale with the Python version alone.

Two facts follow from the tables. Partial mode arms one family of six: the mode is
parametrized over every backend, but the only assertion is about environment
variables. And the container grid runs one interpreter against a
`requires-python` that claims four: raising it means building and tagging the
per-version images, since the grid asks for `:latest`. That is not a code change:
the five `Dockerfile*` already take `ARG PYTHON_VERSION`, and the Makefile
derives it from the venv's interpreter. What holds it back is runtime, since the
container job is already budgeted at 300 minutes for a single version, most of it
QEMU booting under emulation.

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
- **The unprivileged `unshare` rows run without a `/proc`.** They prove the confinement without the APIs that
  need `/proc`; the rows with a mounted `/proc` need `--privileged`.
- **Partial mode arms one guard family of six.** The mode is parametrized over
  every backend, but the only assertion is about environment variables — see
  section D.
- **The container grid runs one interpreter against a four-version support
  claim.** `requires-python = ">=3.11.5,<3.15"`, while `containers.yml` pins
  `3.13` and the grid asks for `:latest`. The unit, integration and sample
  suites cover the four — see section D.
- `call_llm()` in `tst_usage.py` is defined but never invoked — dead code, not a
  provider test.
