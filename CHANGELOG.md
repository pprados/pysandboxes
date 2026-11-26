# Changelog

| Python   | OS-Sandbox    | OS         | Feature   |
|----------|---------------|------------|-----------|
| ✅ 3.11   | ✅ none         | ✅ Linux    | ✅ Env     |
| ✅ 3.12   | ✅ subprocess   | ✅ WSL      | ✅ Files   |
| ✅ 3.13   | ✅ landlock     | ✅ MacOS   | ✅ Network |
| ✅ 3.14   | ✅ bwrap        | ✅ Windows | ✅ Import  |
| ✅ 3.15   | ✅ firejail     |            | ✅ API     |
|          | ✅ unshare       |            | ✅ Eval    |
|          | ✅ qemu          |            |   |
|          | ✅ qemu-microvm  |            |           |
|          | ✅ sandbox-exec  |            |   |
|          | ✅ gVisor        |            |           |
|          | ✅ smolvm        |            |           |
|          | ✅ docker-sandbox |            |           |
|          | ✅ appcontainer  |            |           |
|          | ✅ Docker¹       |            |     |
|          | ✅ Podman¹       |            |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.


## [0.15.0] - 2026-11-26

### Added

- `docker-sandbox` provider (`os-sandbox=docker-sandbox`): the code runs in a Docker Sandboxes micro-VM with its own kernel, with per-sandbox network rules and optional credential injection through the proxy of `sbx` (Linux, needs `sbx` and a guest template).

## [0.14.0] - 2026-11-25

### Added

- Python 3.15 is supported: the dynamic-code guard now covers the new `profiling` modules and the startup-file execution of `site`, and a `lazy import` of a denied module is refused when it resolves. The Docker images are published for 3.15 too.

### Fixed

- `bwrap`: `net-resolve=runtime` no longer fails to resolve names when `/etc/resolv.conf` is a regular file and the profile exposes `/etc`.

## [0.13.0] - 2026-11-23

### Added

- `unshare`, `bwrap`, `gvisor`: `net-resolve=runtime` now opens the IPv6 addresses of an allowed name as well as the IPv4 ones; without `ip6tables` the sandbox stays IPv4 only, and the host resolvers may now be IPv6.

### Changed

- `qemu`, `qemu-microvm`: the guest no longer has IPv6, so a program cannot reach an address that the guest's IPv4-only firewall does not filter.

### Fixed

- Invalid evaluation limits and malformed profile names are rejected, and evaluation timers are cleaned up on interruption.
- Sandbox timeouts stop unfinished calls and clean up their processes before the sandbox can be reused.
- Nested sandbox contexts now refuse a different policy instead of silently reusing the active sandbox.
- `unshare`, `gvisor`: a network helper crash is now detected, logged and fails the sandbox closed with a clear message instead of leaving later calls to hang.
- `smolvm`: a link already present in the guest image no longer stops the guest from starting.
- `qemu-microvm`: a corrupted or tampered cached kernel is now detected and re-extracted instead of trusted.
- `with sandboxes():` no longer leaks a background thread after the block exits.
- `with sandboxes(os_sandbox="none"):` now really stops the sandbox on exit, so later sandboxes in the same process start properly.
- A sandbox whose shutdown fails is no longer mistaken for one still running; the next one starts fresh and the original failure is still reported.
- `port=` values above 65535 are rejected when the configuration is read instead of crashing the sandbox later.
- A corrupted or hostile serialized immutable dictionary now raises the same error as any other malformed input.
- `sandbox-exec`: `ignore=` patterns with character classes, ranges or a literal `^` or `-` now hide exactly the matching names instead of the opposite set or breaking every file access.
- `net-resolve=runtime`: some allowed host names that were wrongly refused are now learned and opened like any other.
- The network guard now cleanly refuses low-level packet addresses instead of misreading them or crashing.
- `net-resolve=runtime`: the filtering DNS resolver no longer truncates large answers needlessly, avoiding useless retries.
- `eval-max-alloc` now also refuses oversized multiplications and reports every refusal cleanly instead of failing with an unrelated error on huge numbers.
- Evaluated code can no longer reach forbidden attributes through keyword or positional class patterns in `match` statements.
- `locals()` in evaluated code is now refused like `globals()`, so evaluated code can no longer disable the iteration limit.
- `unshare`: the host's DNS configuration is now exposed read-only to the sandbox, so sandboxed code can no longer rewrite it.
- `firejail`: an `ignore=` pattern now hides matching files in every subdirectory, not only at the top level.
- `firejail`: network and system-call filtering options containing `=` are no longer truncated.
- `firejail`: unreachable local DNS resolvers are no longer passed to the jail.
- `bwrap`, `unshare`, `firejail`, `sandbox-exec`, `gvisor`, `smolvm`: a path exposed both read-only and read-write now ends up read-write.
- `qemu`, `qemu-microvm`: a mount path containing a quote or a newline can no longer inject shell commands into the guest.
- `qemu`: an insecure redirect while downloading the guest image is now refused.
- Two `env=` rules giving the same variable different values are now rejected with a clear error.
- Learning mode now learns only the environment variables the code actually reads.
- `bwrap`, `unshare`, `firejail`, `qemu`, `qemu-microvm`: an `ignore=` pattern now also hides matches under every exposed path, like `gvisor` and `smolvm`.
- `qemu`, `qemu-microvm`: a path containing a comma can no longer alter the virtual machine's options, such as turning a read-only mount writable, and an unknown file-sharing security setting now falls back to the default.
- `qemu`: the downloaded guest image is now verified against its published checksum and size, retried once on a mismatch, and checked cheaply on later runs.
- `qemu`: a command now verifies images cached before checksum support existed instead of leaving them unverified.
- Sandbox processes are now always stopped when shutdown, restart or start fails, and no longer leave temporary files or orphan processes behind.
- A single very large output is now streamed in several ordered parts instead of failing the whole call, and is no longer repeated in the final result.
- `qemu.start_timeout` now rejects infinite and invalid values.
- `os-sandbox=none` now runs the sandbox's initialization function, like every other provider.
- The `data-only` result mode now refuses cyclic ordered dictionaries, counters and deques.
- The sandbox's graceful shutdown no longer blocks other work while it waits.
- `python-sb`: a leading `--` before the script name is no longer mistaken for the script.
- `qemu`, `qemu-microvm`: the guest helper that applies learned firewall addresses now listens only on the internal network.
- Modules loaded by hand from a file or a zip archive are now judged by `python-import=` rules.
- Standard-library helpers that compile or run source code are now guarded by `eval-*` rules instead of running that code unchecked.
- Rebuilding code objects from serialized bytecode is now refused like `eval`/`exec` unless dynamic code is allowed.
- `appcontainer`: the sandboxed process can no longer change the host's display settings.
- `appcontainer`: permission changes can no longer be redirected to another file by swapping in a link, including when the path uses short Windows names.
- Running a program with `-m` under any OS provider works again.
- `appcontainer`: a virtual environment changed since its last run is now re-granted, so editable installs import correctly.

## [0.12.0] - 2026-11-13

### Added

- Add the smolvm provider (`os-sandbox=smolvm`): the sandboxed code runs in a hardware-isolated micro-VM with its own kernel, with file, network and environment rules enforced by the host side of smolvm, and a dedicated `python-sb-smolvm` image.
- A `qemu-microvm` profile can now share more than six host directories with the guest instead of failing at start; `qemu.microvm_pcie=auto|true|false` (default `auto`, only when needed) forces or forbids the PCIe bus that makes it possible.
- `PYSANDBOXES_RPC_TIMEOUT` sets the seconds a call into the sandbox may take before the host gives up (120 by default), for a first call that imports a heavy library inside a slow guest.
- `QEMU_START_TIMEOUT` sets the seconds a QEMU guest gets to answer for every profile without a `qemu.start_timeout` key, and a guest that answers after more than half of that time is reported in a warning with the time it took.
- `net-resolve=runtime|pinned` chooses when the host names of `net=` rules are resolved: `runtime` (`unshare`, `bwrap`, `gvisor`, `qemu`, `qemu-microvm`, `subprocess`, `landlock`, `sandbox-exec` and `appcontainer` (Python guard only) and `firejail` (as root; without root it falls back to `pinned`)) resolves them when the program asks, through a filtering resolver that opens the addresses of an allowed name for their TTL and refuses every other name and resolver, so a name whose addresses rotate keeps working, while `pinned` (what applies without the key) freezes their addresses at start.

### Fixed

- Stop printing an `AssertionError` from the sandbox process when it shuts down, with every OS provider.
- The `python-sb-qemu-microvm` image now starts its default profile, which no longer exceeds the microvm host-share capacity.

### Added
- Fall back to a PCIe bus when the 9p shares exceed MMIO
- Qemu.microvm_pcie lifts the MMIO limit on 9p shares
- Os-sandbox=none accepts net-resolve and warns that it adds no OS boundary
- Net-resolve=runtime under firejail without root falls back to pinned
- Net-resolve=runtime for firejail without root, judged by the Python guard
- Net-resolve=runtime for landlock, judged by the Python guard
- Net-resolve=runtime for sandbox-exec and appcontainer, judged by the Python guard
- Net-resolve=runtime for subprocess, judged by the Python guard alone
- Net-resolve=runtime for qemu-microvm
- Net-resolve=runtime for qemu, through a helper process of the guest
- Net-resolve=runtime for firejail, as root
- Net-resolve=runtime for bwrap and gvisor, with integration tests per provider
- Net-resolve=runtime for unshare, with positive and negative integration tests
- Net-resolve=pinned|runtime profile key and runtime name rules in the guard
- Netns iptables enforcer and runtime ruleset
- Runtime DNS filter core, name rules, learned table and filtering resolver
- Relay the standard input of python-sb to the guest
- Build the guest image for the Python of the host and refuse another one
- Bind the exposed paths from a few shares, and keep the config off the disk
- Add the smolvm micro-VM provider

### Fixed
- Wait for the guest helper to listen before the sandboxed program runs
- Make the timeout of a call into the sandbox adjustable, and raise it in the VM samples
- Give a slow runner's guest more time and say how long it took
- Run mypy once per sample in lint_diff
- Avoid the 2 GiB guest hang on the ACPI machine and cover the PCIe fallback end to end
- The one-shot python-sb run under firejail lets the runtime resolver join the jail
- Refuse net-resolve=runtime under firejail without root when the profile is read
- Stop the resolver in one-shot runs, error without an IPv4 resolver, document net-resolve and its limits
- Drop the CA host shares of the default profile in the qemu-microvm image
- Build the smolvm guest archive once per Python version
- Count the daemon the sandbox process registers, so its shutdown balances
- Build the smolvm guest archive once per Python version
- Start the guest with the home that holds the smolvm agent
- Name the guest archive from an ARG the base image does not set as an ENV
- Refuse a script read from the standard input instead of running it empty
- Name the guest archive stamp without PYTHON_VERSION so make help stays free of uv
- Run from the guest image when the package cannot be shared, and make the image run
- Drop the CA host shares of the default profile in the qemu-microvm image

### Security
- Relock soupsieve to 4.1 in the samples
- Relock mcp-server-demo against the current pysandboxes metadata

## [0.11.0] - 2026-11-10

### Added

- The channel between the host and the sandbox now runs over a Unix socket the host binds and hands down, instead of a local TCP port, with the `subprocess`, `landlock`, `bwrap`, `firejail`, `unshare`, `qemu` and `sandbox-exec` providers on Linux and macOS; it falls back to TCP when that is not possible. `remote-endpoint=tcp|unix` forces one or the other.
- Add the Linux x86_64 QEMU microvm provider (`os-sandbox=qemu-microvm`) with direct kernel boot and a dedicated image.
- Allow QEMU microvm profiles to opt selected guest paths into host-share omission when MMIO capacity is exceeded.
- Let QEMU microvm profiles list guest paths (`qemu.microvm_empty_paths`) that the guest creates empty when the host share is dropped for capacity, which lets the CrewAI sample run under `qemu-microvm`.
- Complete the Agno sample's standard-library import whitelist for its HTTP client tests.

### Fixed

- Paths reached through a symbolic link loop are now handled without granting any extra access.
- Links the system cannot resolve keep their absolute path when access rules are checked.
- QEMU guests now expose a CPU model recent enough for NumPy to load.
- With `remote-endpoint=auto`, the `qemu` and `qemu-microvm` providers now fall back to a local TCP port when the installed QEMU, such as 8.2, refuses a Unix socket forward, instead of leaving the guest unreachable; `remote-endpoint=unix` reports the cause.
- The QEMU microvm provider now finds images whose boot files sit on a separate partition.
- Several sandboxes starting at once no longer conflict while preparing the shared QEMU microvm boot files.
- The QEMU microvm capacity check now uses the same acceleration as the real run, so its result matches what the guest gets.
- The samples can now load the modules they need at run time under `qemu-microvm`.

### Security

- Raise `oauthlib` in the CrewAI sample to 4.0.1, which fixes a published advisory.
- A QEMU guest now refuses to run when one of its mounts fails, instead of continuing with partial isolation.
- Code run under `qemu-microvm` is now held to the same isolation guarantees as the other providers.

## [0.10.0] - 2026-11-05

### Added
- Add the gVisor provider (`os-sandbox=gvisor`): the guest runs on a user-space kernel, with file, network and environment rules enforced by the OS, and a dedicated `python-sb-gvisor` image.
- The gVisor provider checks every prerequisite before starting and explains each platform value when one is missing or wrong.

### Changed
- Remove the provider extras (`pysandboxes[bwrap]`, `[firejail]`, `[landlock]`, `[sandbox-exec]`, `[subprocess]`, `[unshare]` and `[all]`): they installed nothing, as a provider needs system tools, not Python packages.

### Fixed
- Preserve standard input for MCP servers launched with `python-sb` in QEMU guests.
- Restarting a bwrap or gVisor sandbox no longer leaves the previous network helper running.
- Code that reads its standard input no longer fails under gVisor.
- The gVisor guest no longer sees the host's devices and processes.

### Security
- Raise sample dependencies to versions that fix published advisories.

## [0.9.0] - 2026-11-04

### Added
- Add the Windows AppContainer provider, which confines files and network with an AppContainer token and runs without administrator rights.
- The sandboxed program gets read-write access to its AppContainer private folder.
- Configuration profiles can be included only on a matching platform, so OS-specific permissions can be kept in separate files.

### Changed
- Document the AppContainer provider's security limits and the local Windows VM workflow.

### Fixed
- The qemu container image for Python 3.11 ships the firewall tools its guest needs, not only their libraries.
- A hosts file line that does not start with an address is ignored instead of disturbing name resolution.
- The temporary directory is found before the guards are armed.
- The sandbox provider is loaded even when its startup hook does not run.
- The AppContainer provider hides the private folder location from the sandboxed program.
- The AppContainer provider masks ignored paths reliably and removes its access grants after each run, without relying on PowerShell.
- The AppContainer provider no longer creates a temporary directory when no OS sandbox is selected.
- The samples, including the CrewAI one, run on Windows.

## [0.8.0] - 2026-10-31

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
- A `firejail` sandbox that exits before it starts, on the failed ARP probe of the address it picked on the bridge, is launched again, up to three times, instead of failing the run.
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
