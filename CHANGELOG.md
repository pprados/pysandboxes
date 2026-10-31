# Changelog

| Python   | OS-Sandbox    | OS         | Feature   |
|----------|---------------|------------|-----------|
| ✅ 3.11   | ✅ none         | ✅ Linux    | ✅ Env     |
| ✅ 3.12   | ✅ subprocess   | ✅ WSL      | ✅ Files   |
| ✅ 3.13   | ✅ landlock     | ✅ MacOS²   | ✅ Network |
| ✅ 3.14   | ✅ bwrap        | ◐ Windows² | ✅ Import  |
| ☐ 3.15   | ✅ firejail     |            | ✅ API     |
|          | ✅ unshare       |            | ✅ Eval    |
|          | ✅ qemu          |            | ☐ Source  |
|          | ✅ sandbox-exec  |            | ☐ Regexp  |
|          | ✅ Docker¹       |            | ☐ DoS     |
|          | ✅ Podman¹       |            |           |
|          | ☐ gVisor        |            |           |
|          | ☐ micro-VM      |            |           |
|          | ☐ App container |            |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.


## [0.0.0] - 202X-XX-XX

### Added
- Present Py-Sandboxes as an execution harness for Python in the README.
- Add the macOS Seatbelt `sandbox-exec` provider, which receives its profile through a private pipe and resolves names through mDNSResponder, with documented host-filtering and DNS limitations.
- Set `PYSANDBOXES_LOG_LEVEL` to choose the log level of `python-sb`, of `sandboxes()` and of their sandboxed process.
- Add `make crosshair`, which looks for counterexamples to the PEP 316 contracts written in the docstrings of the pure helpers.
- Learning summarizes at info level where the learned rules come from, only when a rule was learned.

### Changed
- `make publish-*` no longer asks for a confirmation before it signs and pushes the tag, so a release can run from a script.
- Allow `os.getcwd()` and `os.getcwdb()` to report the current directory without granting file access.
- A profile generated on macOS names `sandbox-exec` when it is available, instead of `subprocess`.
- A device, a FIFO or a socket is exposed as the file itself, and `/dev/null`, `/dev/zero`, `/dev/urandom` and `/dev/random` need no rule: `landlock` and `firejail` no longer open the whole `/dev`, and learning no longer writes `expose-rw=/dev`.
- `landlock` gives the sandbox a temporary directory of its own, removed when the daemon stops, instead of the host's whole `/tmp`: `tempfile` works as before, but a hard-coded `/tmp/...` path is now refused.

### Fixed
- `shutil.disk_usage()` and `os.statvfs()` now obey file access rules, on Windows too.
- Learn module source access found by `importlib`, so `python-sb -m package.module` works after learning without granting project-root reads.
- `python-sb -m` no longer judges the package it runs before the import guard is armed.
- `python-sb app/script.py` runs again under a profile that exposes only `./app`, such as a learned one.
- Learning no longer drops callers located under the repository.
- `os.readlink()` can read a link that a rule names itself.
- Under `qemu`, a device rule uses the guest's own `/dev` instead of sharing the host's.
- The samples' partial-mode tests run under the provider named by `OS_SANDBOX` instead of always under `subprocess`, so `make sample-tests` now exercises that provider in both modes.
- The `qemu` container images, including the Ubuntu 24.04 and Python 3.11 guests, no longer fail with `iptables-restore failed: free(): invalid pointer`, and every image is now checked for it.
- A `firejail` sandbox that exits before it starts, on the failed ARP probe of the address it picked on the bridge, is
  launched again, up to three times, instead of failing the run.
- A `net=` port list with a range followed by a single port, such as `80-90,85`, no longer fails with a `TypeError`.
- `os.path.realpath()` of the interpreter no longer fails when it is reached through a `uv` link, which made `pytest --cov` stop every sandboxed process.
- An immutable dictionary refuses a forged pickle state.
- The configuration and network-filter pipes of a remote sandbox are now private to their user.

### Security
- Raise `virtualenv` to clear its advisories.
- Relock the samples' dependencies, including `pyasn1`, `joserfc`, `langgraph-sdk`, `brotli` and `gitpython`, to versions without known vulnerabilities.

## [0.7.0] - 2026-10-22

First public release.

### Added
- Two coding-agent skills: one learns the rules a new feature needs from its tests and asks before granting them,
  the other lists the rights a change adds to the `.py-sandboxes` files, graded by risk, with the code that needs
  each; and a GitHub workflow to copy into a project, which comments that list on a pull request
- `python-sb` runs a Python script, a module or an interactive session
  under the rules of a `.py-sandboxes` file, in place of `python`
- *complete* mode, which sandboxes the whole application, and *partial*
  mode, which runs only the functions marked with `@sandbox` in a
  sandboxed child process, through the `sandboxes()` context manager
- Control of environment variables, imports, files and network access,
  denied by default and granted by whitelist
- Control of sensitive API calls, independent of import rights: an
  import right is not a call right. A registry of 152 sensitive
  functions in eight categories (`process-exec`, `process-control`,
  `privileges`, `threads`, `native`, `introspection`, `dynamic-code`,
  `deserialization`) is denied by default, and permissions are granted
  with `python-api=ALLOW:<category>|<function>` (and `DENY:`), resolved
  by specificity
- Control of code that arrives as a string: a source given to `eval()`,
  `exec()` or `compile()` is parsed, checked against a sub-language,
  rewritten so the remaining risks are enforced while it runs, and
  executed under a budget and a timeout the caller can recover from.
  Five list keys (`eval-syntax`, `eval-call`, `eval-attribute`,
  `eval-import`, `eval-magic`) say what the sub-language accepts,
  `eval-namespace` what it sees, `eval-timeout` and the `eval-max-*` keys
  bound nodes, depth, iterations, call depth, allocations and leaked
  threads. Only code reaching those three builtins is transformed: the
  application's own modules are untouched. See `wiki/eval.md`
- Require a host bridge for Firejail network filtering and test its OS-level rules in the provider matrix
- The value a sandboxed function returns is decoded in the calling process under a guard. By default it accepts
  values only: primitive data and containers, with paths, dates and time zones, decimals, fractions, UUIDs and IP
  addresses, and rebuilds no other class. `remote-result-mode=objects` rebuilds any object, and refuses the
  classes and functions that would act in the calling process: processes, files, signals, nested pickles, code
  objects
- Learning mode (`--learn`), which records what an application really
  uses and writes the matching rules
- Control of the life cycle of the sandbox daemon, restarted when needed
- Seven OS providers, selected with `OS_SANDBOX=` or `--os-sandbox`:
  - `none`: no sandbox at all, plain Python, for testing and debugging
  - `subprocess`: a separate interpreter process, still no OS boundary
  - `landlock`: the process restricts itself, needs no privilege
    (kernel 5.13+ for files, 6.7+ for network)
  - `bwrap`: bubblewrap namespaces, disk and network filtering
  - `firejail`: disk and network filtering
  - `unshare`: namespaces driven directly, with `slirp4netns` and
    `iptables`
  - `qemu`: full OS and CPU emulation, KVM when available
- Container images on Docker Hub, one per provider family, for Python
  3.11 to 3.14
- Thirteen samples: `quick-demo`, and twelve agent frameworks, each with
  its own rules, test suite and interactive chat: `agno-demo`,
  `autogen-demo`, `crewai-demo`, `google-adk-demo`, `langchain-demo`,
  `langgraph-demo`, `mcp-client-demo`, `mcp-server-demo`,
  `openai-agents-sdk-demo`, `pydantic-ai-demo`, `smolagents-demo` and
  `strands-agents-demo`
- Python 3.11.5 to 3.14
- Configuration profiles can be included only when `sys.platform` matches, so OS-specific permissions can be kept
  in separate files
- `unshare.proc=none` runs the `unshare` sandbox without a `/proc`, and `unshare` warns, when a container refuses
  to mount `/proc`, with the settings to change or this option. `shutil.rmtree`, `os.fwalk` and `dir_fd=` calls
  on a directory opened by `os.open` keep working without `/proc`
- A generated `.py-sandboxes` names `landlock` as its default provider (`os-sandbox=${OS_SANDBOX:-landlock}`) on
  Linux when the kernel supports it, and `subprocess` otherwise, with a warning when Linux lacks Landlock; learning
  itself still always runs under `subprocess`
- A profile whose `python-api` rules grant `eval`, `exec` or `compile` while it also carries `eval-*` rules is
  refused at load, with each `eval-*` line to comment out

### Notes
- `native` and `introspection` are detection and friction, not a
  barrier: sandboxed code can undo Python-level patches (see
  `wiki/weaknesses.md`). The OS providers are the real barrier.
- A single call can cross several guarded doors in series, for example
  `subprocess.run` reaches `Popen`, so for `process-exec` the category
  form is usually the right one. Each refusal names the door it stopped
  at.
