# Contributing to PySandboxes

PySandboxes runs code its caller does not trust, so a contribution is judged first on whether the sandbox
still holds after it. This page says how to get started, how to propose a change, and what a pull request
must carry. It is also the checklist the maintainer's review applies.

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security issues first

A vulnerability is never reported in an issue or a pull request, not even as a fix. Follow
[`SECURITY.md`](SECURITY.md): a private GitHub security advisory, or `github@prados.fr`. The same page lists what
does not count as a vulnerability, such as the known Python-layer weaknesses in
[`wiki/weaknesses.md`](wiki/weaknesses.md); those are welcome as ordinary issues.

## Getting started

Python 3.11.5 to 3.14, with [uv](https://docs.astral.sh/uv/) exclusively. Every OS provider is a Linux technology, except
the deprecated Seatbelt `sandbox-exec` of macOS, so what you can run depends on your system:

| Your system | What runs | Needs |
|---|---|---|
| Linux, or WSL2 | everything: the Python layer and the providers `landlock`, `bwrap`, `firejail`, `unshare`, `qemu` | the packages and kernel settings below |
| macOS | the Python layer over `subprocess` and the `sandbox-exec` provider, which is what `cross-os.yml` proves on macOS | Xcode command line tools, uv; GNU sed, jq and coreutils (`make setup-macos`) for the release-script tests, which are left out without them |
| native Windows | the Python layer over `subprocess` | uv, git, GNU make, a bash (Git Bash) |

On macOS and Windows, a change that touches a Linux kernel-backed provider is tested in a Linux VM (Lima, Colima, Multipass
or UTM on a Mac) or in WSL2 (`wsl --install -d Ubuntu-24.04` on Windows). Prefer WSL2 on Windows: the Makefile is
written for bash, and WSL2 gives you the providers too. Landlock is reported to work under WSL2; `make doctor`
tells you whether your kernel has it. A VM on an Apple Silicon Mac or in WSL2 has no nested KVM in the general
case, so `qemu` falls back to the slow TCG row there.

```bash
git clone https://github.com/pprados/pysandboxes.git
cd pysandboxes
git checkout develop
make init        # on a bare system without make: scripts/setup/init.sh
```

`make init` detects the system (Linux, WSL2, macOS, Git Bash), installs what it lacks after asking you, runs
`uv sync --python-preference only-managed --group dev --group test --group lint`, and ends with `make doctor`.
The `uv`-managed Python is deliberate: a distribution Python, such as Ubuntu 24.04's 3.12.3 that `uv` would pick
otherwise, fails 4 unit tests and 29 provider tests of this repository. On Linux and WSL2 it installs these
packages with `apt-get` or `dnf`: `git`, `make`, `curl`, a C compiler, `bubblewrap`, `firejail`, `slirp4netns`,
`iptables`, `iproute2`, `qemu-system-x86`, `qemu-utils` and `genisoimage`, then `uv` if it is missing. `YES=1 make init`
accepts every question except the one on AppArmor.

Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor, and `bwrap` and `unshare` need them. `make init`
offers `kernel.apparmor_restrict_unprivileged_userns=0`, now and at every boot (`/etc/sysctl.d/60-pysandboxes.conf`).
That widens the kernel attack surface of your workstation (see [`wiki/unshare.md`](wiki/unshare.md)), so it is
asked separately, and only `RELAX_APPARMOR=1` accepts it without a terminal. Declining leaves the `bwrap` and
`unshare` rows skipped or failing.

`make doctor` changes nothing. It lists each tool and kernel setting, `[ok]` or `[missing]`, and what a missing
one costs: a provider whose tool is absent skips its tests, and a skipped test proves nothing about it. To run
only one step, `make setup-linux`, `make setup-macos` or `make setup-windows`.

A plain `uv sync` installs the `dev` group only and removes the linters. `make help` lists every target.

### Containers and the Windows and macOS VMs

These are the maintainer's means to prove the whole matrix from a Linux workstation. A pull request does not need
them: CI runs lint and the unit tests, and `cross-os.yml` runs macOS and Windows.

- `make container-tests` needs Docker or Podman, and minikube for the Kubernetes rows (`make minikube-ready`).
- `make windows-vm` starts a Windows 11 VM in Podman or Docker (`dockurr/windows`). It needs `/dev/kvm` and takes
  about 30 minutes the first time. `make windows-tests` then runs the `cross-os.yml` steps in it.
- `make init-macos-vm` builds an Intel macOS VM with [OSX-KVM](https://github.com/kholia/OSX-KVM) on a Linux x86_64
  host with KVM. Read what it prints and answer `yes` before it downloads anything: Apple's licence allows macOS in a
  virtual machine on Apple-branded hardware only, the guest is an Intel macOS (it says nothing about Apple
  Silicon), and the installation of macOS itself is interactive, through a VNC viewer. The script prints each manual
  step, and you run `make init-macos-vm` again after them: it then installs uv, GNU sed and jq, checks the compiler and builds an
  OpenSSL inside the VM, which `cryptography` needs on Python 3.11 and 3.12. The files live under
  `~/.pysandboxes/macos-vm`; set `OSX_KVM_DIR` to use another place. `make macos-vm` boots it and
  `make macos-tests` runs the `cross-os.yml` steps in it. If you own a Mac, you do not need this VM: run the suites
  on the Mac.

- `make linux-vm` creates a clean Ubuntu 24.04 VM with [Multipass](https://multipass.run) (4 CPUs, 6 GB, 30 GB; set
  `LINUX_VM_CPUS`, `LINUX_VM_MEMORY`, `LINUX_VM_DISK`), and `make linux-tests` sends the checkout to it, runs
  `make init` there, then the unit and integration suites: the setup of a contributor on a stock Linux. Fewer than 4
  CPUs make the daemons of the integration suite time out at startup. `make linux-vm-stop` keeps the disk,
  `make linux-vm-clean` deletes it.

### Where things are

| Path | What it holds |
|---|---|
| `pysandboxes/sandboxes_api.py` | the public API: `@sandbox` and the `sandboxes()` context manager |
| `pysandboxes/py_sandbox.py` | the Python layer, which patches the standard library at run time |
| `pysandboxes/_os_sandbox.py` | the registry of OS providers, from `none` to `sandbox-exec` |
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
- one page per OS provider (`bwrap.md`, `firejail.md`, `unshare.md`, `qemu.md`, `landlock.md`, `sandbox-exec.md`), and
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

The goal is to keep Python code contained inside the sandbox, not to remove every flaw Python has. The Python
layer intercepts the pure-Python APIs (`open`, `socket`, imports, sensitive calls); it is friction, and
introspection can undo it, as [`wiki/weaknesses.md`](wiki/weaknesses.md) lists. What it cannot see, such as
`ctypes`, compiled extensions or direct syscalls, is left to the OS provider, which is the boundary. Flaws of
CPython or of a library, unsafe code written by the sandboxed program itself, and the positions listed under
"What does not count" in [`SECURITY.md`](SECURITY.md#what-does-not-count) are out of scope, as long as the rules
still hold: anything that lets sandboxed code do what the rules deny while the OS layer is configured to hold
stays in scope ([`SECURITY.md`](SECURITY.md#what-counts-as-a-vulnerability)).

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

### Pull request templates

The default template fits any change. `.github/PULL_REQUEST_TEMPLATE/` holds one template per kind of
contribution, with the checks of that kind. Pick one by adding `?template=<file>` to the compare URL, for
example `https://github.com/pprados/pysandboxes/compare/develop...<branch>?template=fix.md`.

| Template | For |
|---|---|
| `fix.md` | a bug fix outside the security model |
| `feature.md` | a new option, API or behaviour outside the security model |
| `security-model.md` | a guard, `eval_*`, an OS provider or rule parsing |
| `tests.md` | tests only |
| `workflow.md` | a GitHub workflow or a CI script |
| `docs.md` | `README.md`, `wiki/`, `CHANGELOG.md`, samples' documentation |

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

### Security model

- Default deny stays: no default, fallback or rule that widens what sandboxed code may do.
- A change to a guard, to `eval_*`, to a provider or to rule parsing says which layer it touches (Python or
  OS) and comes with a test proving the refusal still holds.
- Nothing may let sandboxed code widen its own permissions: rule files, learning-mode output, configuration
  paths.
- A new sensitive function is registered in `guard_api` under one of its categories.
- A change is judged on whether sandboxed code stays contained, not on whether it closes every Python flaw
  (see [The security model](#the-security-model)). Leaving an out-of-scope weakness open is not a defect;
  widening permissions or weakening default deny always is.

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

CI runs lint and unit tests on every pull request. The maintainer reviews the diff from their own machine,
with the `pysandboxes-pr-review` skill (`.agents/skills/`). That review:

- applies the requirements above, read from `develop`, so a pull request cannot change the criteria it is
  reviewed against;
- reads the pull request only through its diff, and refuses to review a head that moved since it was
  requested: ask again to review new commits;
- only posts comments: it never runs the pull request's code, never pushes, never approves.

CI on a pull request runs lint and unit tests only; the integration suite runs nightly on `develop`, after the
merge. So before merging a pull request that touches a provider, the remote layer or a full workflow, a
maintainer pushes its reviewed head to a branch of this repository and runs `full-gate.yml` on it.

The decision to merge always stays with a maintainer.

## License

Contributions are accepted under the [Apache License 2.0](LICENSE.txt), the license of the project.
