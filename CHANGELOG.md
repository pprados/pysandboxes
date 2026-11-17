# Changelog

| Python   | OS-Sandbox    | OS         | Feature   |
|----------|---------------|------------|-----------|
| ✅ 3.11   | ✅ none         | ✅ Linux    | ✅ Env     |
| ✅ 3.12   | ✅ subprocess   | ✅ WSL      | ✅ Files   |
| ✅ 3.13   | ✅ landlock     | ✅ MacOS   | ✅ Network |
| ✅ 3.14   | ✅ bwrap        | ✅ Windows | ✅ Import  |
| ☐ 3.15   | ✅ firejail     |            | ✅ API     |
|          | ✅ unshare       |            | ✅ Eval    |
|          | ✅ qemu          |            |   |
|          | ✅ qemu-microvm  |            |           |
|          | ✅ sandbox-exec  |            |   |
|          | ✅ gVisor        |            |           |
|          | ✅ smolvm        |            |           |
|          | ✅ appcontainer  |            |           |
|          | ✅ Docker¹       |            |     |
|          | ✅ Podman¹       |            |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.


## [0.0.0] - 202X-XX-XX

### Added

- `unshare` and `gvisor`: a `slirp4netns` crash (or an external kill) outside a deliberate shutdown is now detected and logged, and fails the sandbox closed with a clear message instead of leaving every later call to retry or hang against a network that is down for good.
- `smolvm`: a symlinked path already present in the guest image no longer stops the guest's init script under `set -e`; the link is now forced into place instead.
- `qemu-microvm`: the cached kernel/initrd pair extracted from the guest image now gets a checksum sidecar, like the image download does, so a corrupted or tampered cache entry is re-extracted instead of trusted as-is.
- `with sandboxes():` no longer leaks a background thread running an idle event loop forever after the block exits, when it started with no event loop already running.
- `with sandboxes(os_sandbox="none"):` (and the signal handler it installs) now actually stop the daemon on exit instead of believing, from that point on, that every later `with sandboxes():` in the same process is a nested call and never starting a real one.
- A daemon whose shutdown fails is no longer mistaken for one still running: the next `with sandboxes():` now starts a real new daemon instead of reusing the dead one, and the original failure still reaches the caller.
- Reject `port=` values above 65535 at config parsing instead of letting the sandbox daemon crash later with an opaque `OverflowError` from `socket.bind()`.
- A corrupted or hostile `ImmutableDict` pickle stream with a non-hashable key now raises `ValueError` like every other malformed stream, instead of `TypeError`.
- `sandbox-exec`: an `ignore=` pattern with a literal `^` in a `[...]` character class (e.g. `[^abc]`, fnmatch's literal class, not a regex negation) is now translated to a Seatbelt regex that denies that class, instead of one that Seatbelt reads as negated and denies the opposite set of names.
- `sandbox-exec`: an `ignore=` pattern with a character-class range (e.g. `[a-z]`, `[!a-z]`) or a literal `-` at either end of a class (e.g. `[-abc]`, `[abc-]`) is now translated to match fnmatch's semantics, instead of a trailing `-` making the whole Seatbelt profile fail to compile ("unterminated bracket expression") and every file access under that os-sandbox fail with it.
- `net-resolve=runtime`: a host name whose first resolution attempt needed the socket's own type to succeed is now learned and opened like any other allowed name, instead of being refused by the default policy.
- The network guard now refuses `bind()`, `connect()`, `connect_ex()` and `sendto()` on an `AF_PACKET` (and similarly-shaped) address with a clean refusal instead of resolving its interface name as a hostname or crashing on its socket type.
- `net-resolve=runtime`'s filtering DNS resolver now honors a client's own EDNS0 buffer size instead of always truncating a UDP answer over 512 bytes, so a resolver-aware program no longer pays for a needless TCP retry.
- `eval-max-alloc` now also refuses an integer multiplication (`a * b`) in evaluated source whose result would exceed it, and reports every such refusal, including the pre-existing `**` and `<<` ones, without converting the oversized operand to decimal, which used to raise `ValueError` instead of the refusal itself once past CPython's own int-to-str digit limit.
- A `case Cls(name=binding):` keyword attribute pattern in evaluated source is now checked against `eval-attribute`/`eval-magic` and the non-overridable frame-capture deny, closing the route `gi_frame`, `__class__` and any other attribute took around `__sb_getattr__` through the `MATCH_CLASS` opcode's own, unguarded `getattr`.
- `locals()` in evaluated source is now refused like `globals()`, instead of handing back the live namespace: evaluated code rebinding `locals()["__sb_tick__"]` used to silence every later tick, defeating `eval-max-iterations` and leaving only the cooperative timeout standing.
- `unshare`: the host's real `/etc/resolv.conf` and `/etc/hosts` are now bind-mounted read-only into the sandbox instead of writable, closing a route for sandboxed code to rewrite the host's DNS configuration through the shared inode of a bind mount.
- `firejail`: an `ignore=` pattern now hides every matching file under the current directory instead of only a literal path at the jail's root, so `sub/.env` is blacklisted like `.env` is.
- `firejail`: a `firejail.net=`, `firejail.seccomp=`, `firejail.seccomp.keep=` or `firejail.seccomp.block=` value containing `=` is no longer truncated at the first one.
- `firejail`: a non-loopback upstream DNS resolver no longer pulls every loopback resolver back into `--dns` once found, since the host's own loopback is unreachable from inside the jail's network namespace.
- `bwrap`, `unshare`, `firejail`, `sandbox-exec`, `gvisor` and `smolvm`: a path exposed both `expose-ro` and `expose-rw` now ends up read-write, the broader right (`expose-rw`) winning, instead of read-only.
- `qemu` and `qemu-microvm`: the guest working directory is now shell-quoted in the bootstrap script instead of interpolated raw into `cd "..."`, closing a shell-injection route for a mount path containing a quote or a newline.
- `qemu`: a redirect from `https://` to `http://` while downloading the guest image is now refused instead of silently followed.
- Two `env=` rules giving the same exact variable different values are now rejected at parse time with a clear error, instead of the last one silently winning.
- Learning mode no longer mistakes a read-back of a paused `os.environ` iteration for a real use when another iteration is nested inside it; only variables the code actually reads are now learned.
- `bwrap`, `unshare`, `firejail`, `qemu` and `qemu-microvm`: an `ignore=` pattern now also hides a match under every `expose-ro=`/`expose-rw=` path, not only under the current directory, matching `gvisor` and `smolvm`.
- `qemu` and `qemu-microvm`: a host path or image path containing a comma is now escaped before being placed in a `-virtfs`/`-fsdev`/`-drive` argument, instead of letting the comma start an unintended QEMU sub-option (e.g. turning a read-only mount writable); an unknown `qemu.virtfs_security_model` value now falls back to the default instead of being forwarded as-is.
- `qemu`: the downloaded guest image is now hashed while it streams to disk and verified against a checksums file fetched next to it (or `PYSANDBOXES_QEMU_IMAGE_SHA256` for a custom URL), refusing a standard Debian/Ubuntu download outright when no digest is available, retrying once on a mismatch, and checking the byte count against `Content-Length` even without a checksum; a verified cached image gets a `.sha256` sidecar so a later run only re-checks its size and mtime instead of re-hashing it.
- The subprocess-based daemon (`subprocess`, `landlock`, `bwrap`, `firejail`, `unshare`) now kills its sandbox process on every failure of the remote shutdown call, instead of an unnamed one always raising an `AssertionError` and leaving the process running; a restart that fails after already launching a new process now kills it too, instead of leaking it; a failed start now removes the private Unix-socket directory it had created, instead of leaving it behind; the sandbox process is now asked to die with its launcher, through `PR_SET_PDEATHSIG` on Linux.
- A single `print()` or write far above the SSE line budget is now split into several ordered `stdout`/`stderr` events instead of refusing the whole call, or letting one oversized line through to the parent's HTTP reader, which refused it opaquely; the final message no longer repeats the already-streamed output.
- `qemu.start_timeout` now rejects `nan` and `inf` like `PYSANDBOXES_RPC_TIMEOUT` already does, instead of waiting on a value that can never be reached.
- `os-sandbox=none` now runs the sandbox's `init_fn`, like every other provider.
- The result channel's `data-only` mode now refuses a cyclic `OrderedDict`, `Counter` or `deque`, instead of letting it through unchecked because the three are also listed as opaque value types.
- The sandbox daemon's own graceful-shutdown delay no longer blocks the event loop for its duration.
- `python-sb`: a leading `--` before the script name on the sandboxed command line is no longer passed through as if it were the script itself.
- `qemu` and `qemu-microvm`: the guest-side helper that applies a learned firewall address now listens only on the guest's user-mode-network address instead of every guest interface.
- A loader built directly with `importlib.util.spec_from_file_location`/`module_from_spec` and run with `exec_module`, including under a forged spec name such as `"pysandboxes"`, no longer runs as a module in the user's own code without ever being judged by a `python-import=` rule.
- `eval-*`: calling a stdlib entry point that forwards caller-supplied source to `compile`/`exec`/`eval` directly, such as `importlib.abc.InspectLoader.source_to_code`, `SourceFileLoader.get_code`, `code.InteractiveInterpreter.runsource`, `timeit.timeit` or `runpy.run_path`, no longer runs that source unguarded with no `eval-*` rule declared and no `python-api=ALLOW:dynamic-code` grant, instead of being mistaken for the library's own code generation.
- `marshal.loads`/`marshal.load` are now refused like `eval`/`exec`/`compile` when called directly with no `eval-*` rule declared and no `python-api=ALLOW:dynamic-code` grant, instead of rebuilding and handing back a runnable code object unguarded.
- `appcontainer`: the sandboxed process's Job Object now also restricts `DISPLAYSETTINGS`, completing the UI lockdown instead of leaving the host's display configuration reachable.
- `zipimport.zipimporter.load_module`, called directly in the user's own code, no longer execs a zip member without ever being judged by a `python-import=` rule.
- `eval-*`: a positional `case C(x):` pattern against anything but one of the eleven builtin types CPython's `MATCH_CLASS` opcode special-cases (`bool`, `bytearray`, `bytes`, `dict`, `float`, `frozenset`, `int`, `list`, `set`, `str`, `tuple`) is now refused instead of reading `C.__match_args__`'s attributes unguarded, past `eval-attribute` and even the non-overridable frame-capture deny; the keyword form `case C(attr=x):` is unaffected.
- `gvisor` and `bwrap` now reserve their slirp4netns API socket path through the same helper `unshare` uses, instead of each duplicating the create-then-unlink dance inline.
- `appcontainer`: a path's ACL is now granted or revoked on a verified, held-open handle instead of by name, closing a race where a junction or symlink swapped in after planning could redirect the change to another object.
- Running a program with `-m` under any OS provider no longer denies `marshal.loads`/`builtins.compile` on the entry module's own bytecode cache with no `python-api=ALLOW:dynamic-code` grant declared, a regression that broke every `-m` launch.
- `appcontainer`: a venv resynced since its last run (`uv sync`, a reinstalled editable package, a rebuilt `.venv`) now gets its interpreter tree re-scanned for the AppContainer grant instead of reusing a cache keyed only on the venv's own path, which could leave a newly written file, notably an editable install's own `.pth`, without the read access needed to import it; this could make an editable install's own module fail to import under `appcontainer` whenever the sandboxed program's working directory happened not to be the project root (a `-m` launch from the project root masked it, since Python then finds the package through its own directory on `sys.path` regardless of the `.pth` file).
- `qemu`: `python -m pysandboxes.remote.qemu_fetch_image --migrate-cache` now verifies a cached image downloaded before the checksum feature existed against its own upstream checksums and writes its sidecar on a match, instead of leaving it unverified for good.

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
