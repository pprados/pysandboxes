# Changelog

| Python   | OS-Sandbox    | OS        | Feature   |
|----------|---------------|-----------|-----------|
| ✅ 3.11   | ✅ none        | ✅ Linux   | ✅ Env     |
| ✅ 3.12   | ✅ subprocess  | ☐ MacOS   | ✅ Files   |
| ✅ 3.13   | ✅ landlock    | ☐ Windows | ✅ Network |
| ✅ 3.14   | ✅ bwrap       |           | ✅ Import  |
|          | ✅ firejail    |           | ✅ API     |
|          | ✅ unshare     |           | ☐ Source  |
|          | ✅ qemu        |           | ☐ Regexp  |
|          | ✅ Docker¹     |           | ☐ DoS     |
|          | ✅ Podman¹     |           |           |
|          | ☐ gVisor      |           |           |
|          | ☐ micro-VM    |           |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.

## [0.0.0] - 202X-XX-XX

### Changed
- Clarify platform support, security limits, and provider test coverage in the README and wiki
- A new rule file no longer includes `./.local.py-sandboxes` by default: the line is commented out, and accepting
  local rules from the current directory is the user's decision
- The samples' documentation no longer claims that learning mode cannot produce `net=` rules: it does, and each one
  needs review
- A profile whose `python-api` rules grant `eval`, `exec` or `compile` while it also carries `eval-*` rules is
  refused at load, with each `eval-*` line to comment out: the grant ran the code unguarded and left them unused

### Fixed
- Learning mode no longer writes a rule under `/proc`: a library reading `/proc/stat` at import produced
  `expose-ro=/proc`, which exposed every process's environment and command line
- Under `bwrap`, a project reached through a symbolic link runs in its own directory, not silently in `$HOME`
- The sandbox's own server logs go to stderr: on stdout they corrupted an MCP server on a stdio transport
- A host name that no `net=` rule can allow is refused at resolution, with the sandbox's message, under every
  provider: under `bwrap` it failed with a bare "Name or service not known", and no DNS query leaves for it
- Under `bwrap`, a package installed in editable mode, such as a project synced by uv, can be imported
- Under `firejail`, a profile with an `expose-ro=/proc...` rule, which learning mode writes, no longer aborts the launch
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
- A profile can raise one of firejail's limits for itself, e.g. `firejail.rlimit-as=600m` for a framework that maps
  more than 300 MB at import
- Two coding-agent skills: one learns the rules a new feature needs from its tests and asks before granting them,
  the other lists the rights a change adds to the `.py-sandboxes` files, graded by risk, with the code that needs
  each; and a GitHub workflow to copy into a project, which comments that list on a pull request
- `python-sb script.py` reads the `.py-sandboxes` next to the script before the one of the current directory
- Learning mode advises an f-string in place of `str.format()` when it generates an `eval-attribute=format` rule
- First stable version
- Require a host bridge for Firejail network filtering and test its OS-level rules in the provider matrix
- accept *complete* and *selected* mode
- Control environment variables
- Control import list
- Control file and network access
- Control life cycle of the sandbox-daemon (restart if necessary)
- The value a sandboxed function returns is decoded in the calling process under a guard. By default it accepts
  values only: primitive data and containers, with paths, dates and time zones, decimals, fractions, UUIDs and IP
  addresses, and rebuilds no other class. `remote-result-mode=objects` rebuilds any object, and refuses the
  classes and functions that would act in the calling process: processes, files, signals, nested pickles, code
  objects
- The sandbox daemon listens on the loopback when the sandbox shares the host network, and is reached only with
  a per-run token, compared in constant time
- seven os-sandbox providers, selected with `OS_SANDBOX=` or
  `--os-sandbox`:
  - `none`: no OS boundary, the Python layer alone
  - `subprocess`: a separate interpreter process, still no OS boundary
  - `landlock`: the process restricts itself, needs no privilege
    (kernel 5.13+ for files, 6.7+ for network)
  - `bwrap`: bubblewrap namespaces, disk and network filtering
  - `firejail`: disk and network filtering
  - `unshare`: namespaces driven directly, with `slirp4netns` and
    `iptables`
  - `qemu`: full OS and CPU emulation, KVM when available
  Docker and Podman are covered through `unshare`, with `--privileged`
  for Docker.
- twelve samples, each with its own rules, test suite and interactive
  chat: `agno-demo`, `autogen-demo`, `crewai-demo`, `google-adk-demo`,
  `langchain-demo`, `langgraph-demo`, `mcp-client-demo`,
  `mcp-server-demo`, `openai-agents-sdk-demo`, `pydantic-ai-demo`,
  `smolagents-demo` and `strands-agents-demo`
- Code that arrives as a string at runtime is guarded by the `eval-*`
  rules. None of the other layers looks at it, and an emptied
  `__builtins__` stops nothing on its own:
  `().__class__.__base__.__subclasses__()` reaches `Popen` without
  naming a single builtin. A source given to `eval()`, `exec()` or
  `compile()` is parsed, checked against a sub-language, rewritten so
  the remaining risks are enforced while it runs, and executed under a
  budget and a timeout the caller can recover from. Five list keys
  (`eval-syntax`, `eval-call`, `eval-attribute`, `eval-import`,
  `eval-magic`) say what the sub-language accepts, `eval-namespace`
  what it sees, and the `eval-max-*` keys bound nodes, depth,
  iterations, call depth, allocations and leaked threads. Only code
  reaching those three builtins is transformed: the application's own
  modules are untouched and import time is unaffected. See
  `wiki/eval.md`, and `wiki/audit-eval-security.md` for the attacks it
  was tested against.
- Control of sensitive API calls, independent of import rights: an
  import right is not a call right. A registry of 110 sensitive
  functions in eight categories (`process-exec`, `process-control`,
  `privileges`, `threads`, `native`, `introspection`, `dynamic-code`,
  `deserialization`) is denied by
  default, and permissions are granted with
  `python-api=ALLOW:<category>|<function>` (and `DENY:`), resolved by
  specificity. Learning mode records what an application really calls
  and generates the lines.
- `pickle.loads` and `pickle.load`, with their `_pickle` twins, join the
  API registry under a new `deserialization` category: a pickle stream
  names a callable and calls it, so it reaches `os.system` without an
  import and without a source string the `eval-*` layer could parse.
  `pickle.Unpickler` stays unguarded and is documented as such -- it is
  an immutable C type, so neither `__init__` nor `load` can be patched,
  and rebinding the module name to a function would break the
  subclassing a restricted unpickler needs.

### Notes
- `native` and `introspection` are detection and friction, not a
  barrier: sandboxed code can undo Python-level patches (see
  `wiki/weaknesses.md`). The OS-sandboxes remain the real barrier.
- A single call can cross several guarded doors in series — for example
  `subprocess.run` reaches `Popen` — so for `process-exec` the category
  form is usually the right one. Each refusal names the door it stopped
  at.
