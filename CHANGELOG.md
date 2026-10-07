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

### Added
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
