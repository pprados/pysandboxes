# Changelog

| Python   | OS-Sandbox    | OS         | Feature   |
|----------|---------------|------------|-----------|
| ✅ 3.11   | ✅ none        | ✅ Linux    | ✅ Env     |
| ✅ 3.12   | ✅ subprocess  | ✅ WSL      | ✅ Files   |
| ✅ 3.13   | ✅ landlock    | ◐ MacOS²   | ✅ Network |
| ✅ 3.14   | ✅ bwrap       | ◐ Windows² | ✅ Import  |
|          | ✅ firejail    |            | ✅ API     |
|          | ✅ unshare     |            | ✅ Eval    |
|          | ✅ qemu        |            | ☐ Source  |
|          | ✅ Docker¹     |            | ☐ Regexp  |
|          | ✅ Podman¹     |            | ☐ DoS     |
|          | ☐ gVisor      |            |           |
|          | ☐ micro-VM    |            |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.

² The Python layer only, with the `subprocess` provider: every
kernel boundary is a Linux technology.

## [0.0.0] - 202X-XX-XX

### Changed
- Clarify platform support, security limits, and provider test coverage in the README and wiki
- A new rule file no longer includes `./.local.py-sandboxes` by default: the line is commented out, and accepting
  local rules from the current directory is the user's decision
- The samples' documentation no longer claims that learning mode cannot produce `net=` rules: it does, and each one
  needs review
- A profile whose `python-api` rules grant `eval`, `exec` or `compile` while it also carries `eval-*` rules is
  refused at load, with each `eval-*` line to comment out: the grant ran the code unguarded and left them unused
- Docker images tag the pysandboxes version with an `sb` prefix (`3.13-sb0.5.0`), add the exact Python patch
  (`3.13.2-sb0.5.0`), and are rebuilt daily when Python publishes a new patch

### Fixed
- A profile no longer has to allow the sandbox daemon's own modules (uvicorn, fastapi, and the standard library
  they use): learning records only the application's imports
- In partial mode, an import made by the application is judged on its rules even when the module is already
  loaded, by the daemon or by an earlier import
- Learning no longer proposes `python-api=ALLOW:builtins.eval` or `exec` for a source string: that line sent the
  code to the raw builtin, past the `eval-*` rules learning proposes for it
- Learning no longer turns a variable the code sets or removes itself into an `env=` rule, which brought the host's
  value into the sandbox: `load_dotenv()` no longer adds every name of the `.env`
- Learning writes a path under `TRANSFORMERS_CACHE` or `TORCH_HOME` as `${TRANSFORMERS_CACHE}/...` or
  `${TORCH_HOME}/...`, as for the other tool directories, instead of a path of the learning machine
- Under a learned profile, a host name outside the rules is refused by the network rule, not by the import of
  `encodings.idna` the profile never carries
- Learning into a profile that includes another one no longer adds a second `remote-result-mode` rule, which made
  the profile invalid on the next run

### Added
- Two coding-agent skills: one learns the rules a new feature needs from its tests and asks before granting them,
  the other lists the rights a change adds to the `.py-sandboxes` files, graded by risk, with the code that needs
  each; and a GitHub workflow to copy into a project, which comments that list on a pull request
- `python-sb script.py` reads the `.py-sandboxes` next to the script before the one of the current directory
- Learning mode advises an f-string in place of `str.format()` when it generates an `eval-attribute=format` rule
- `python-sb` runs a Python script, a module or an interactive session
  under the rules of a `.py-sandboxes` file, in place of `python`
- *complete* mode, which sandboxes the whole application, and *partial*
  mode, which runs only the functions marked with `@sandbox` in a
  sandboxed child process, through the `sandboxes()` context manager
- Control of environment variables, imports, files and network access,
  denied by default and granted by whitelist
- Control of sensitive API calls, independent of import rights: an
  import right is not a call right. A registry of 121 sensitive
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
- The sandbox daemon listens on the loopback when the sandbox shares the host network, and is reached only with
  a per-run token, compared in constant time
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

### Security
- `posix.chroot` goes through the same path check as `os.chroot`
- `pickle.loads` and `pickle.load`, with their `_pickle` twins, belong to
  the `deserialization` category: a pickle stream names a callable and
  calls it, so it reaches `os.system` without an import and without a
  source string the `eval-*` rules could parse. `pickle.Unpickler` is not
  guarded: it is an immutable C type, so neither `__init__` nor `load`
  can be patched. See `wiki/audit-python-security.md`
- The parent process accepts only an allowlist of classes and pickle
  opcodes when it reads what a sandboxed child returns, so a hostile
  object cannot run code in the parent on the way back. See
  `wiki/transport-unpickle-guard.md`

### Notes
- `native` and `introspection` are detection and friction, not a
  barrier: sandboxed code can undo Python-level patches (see
  `wiki/weaknesses.md`). The OS providers are the real barrier.
- A single call can cross several guarded doors in series, for example
  `subprocess.run` reaches `Popen`, so for `process-exec` the category
  form is usually the right one. Each refusal names the door it stopped
  at.
