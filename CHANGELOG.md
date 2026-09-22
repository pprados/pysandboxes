# Changelog

| Python   | OS-Sandbox    | OS        | Feature   |
|----------|---------------|-----------|-----------|
| ✅ 3.10   | ✅ none        | ✅ Linux   | ✅ Env     |
| ✅ 3.11   | ✅ subprocess  | ☐ MacOS   | ✅ Files   |
| ✅ 3.12   | ✅ landlock    | ☐ Windows | ✅ Network |
| ✅ 3.13   | ✅ bwrap       |           | ✅ Import  |
| ✅ 3.14   | ✅ firejail    |           | ✅ API     |
|          | ✅ unshare     |           | ☐ Source  |
|          | ✅ qemu        |           | ☐ Regexp  |
|          | ✅ Docker¹     |           | ☐ DoS     |
|          | ✅ Podman¹     |           |           |
|          | ☐ gVisor      |           |           |
|          | ☐ micro-VM    |           |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.

## [0.0.0] - 202X-XX-XX

### Added
- First stable version
- accept *complete* and *selected* mode
- Control environment variables
- Control import list
- Control file and network access
- Control life cycle of the sandbox-daemon (restart if necessary)
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
- Control of sensitive API calls, independent of import rights: an
  import right is not a call right. A registry of 110 sensitive
  functions in eight categories (`process-exec`, `process-control`,
  `privileges`, `threads`, `native`, `introspection`, `dynamic-code`,
  `deserialization`) is denied by
  default, and permissions are granted with
  `python-api=ALLOW:<category>|<function>` (and `DENY:`), resolved by
  specificity. Learning mode records what an application really calls
  and generates the lines.
- `posix.chroot` is now guarded by the file layer with the same path
  check as `os.chroot`, which was previously unguarded.
- `pickle.loads` and `pickle.load`, with their `_pickle` twins, join the
  API registry under a new `deserialization` category: a pickle stream
  names a callable and calls it, so it reaches `os.system` without an
  import and without a source string the `eval-*` layer could parse.
  `pickle.Unpickler` stays unguarded and is documented as such -- it is
  an immutable C type, so neither `__init__` nor `load` can be patched,
  and rebinding the module name to a function would break the
  subclassing a restricted unpickler needs.

### Fixed
- `python-sb` honours `TMPDIR` for its host-side run directory instead
  of hardcoding `/tmp`, so it works where `/tmp` is read-only.

### Notes
- `native` and `introspection` are detection and friction, not a
  barrier: sandboxed code can undo Python-level patches (see
  `wiki/weaknesses.md`). The OS-sandboxes remain the real barrier.
- A single call can cross several guarded doors in series — for example
  `subprocess.run` reaches `Popen` — so for `process-exec` the category
  form is usually the right one. Each refusal names the door it stopped
  at.
