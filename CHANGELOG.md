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
- The `.py-sandboxes` shipped inside the calling package is found wherever the current directory is: only a same-named
  directory under the current directory was searched
- On Python 3.11, a plain top-level module calling the API no longer freezes the search for its rule file
- A `${...}` the syntax does not cover, such as `${A:B}`, is a configuration error with its file and line instead of
  freezing the start, and a variable's value is never expanded again
- A sandboxed function raising `SystemExit`, `KeyboardInterrupt` or another `BaseException` fails that call with
  `SandBoxBaseExceptionError`: it no longer kills the sandbox, nor after repeated crashes the application itself
- A sandbox that keeps crashing refuses further calls with an error instead of exiting the application
- `SIGTERM` or `SIGQUIT` inside `with sandboxes()` stops the sandbox then ends the process, instead of being ignored,
  and a failed start leaves the signal handlers untouched
- `uvx python-sb` returns the script's exit code
- `ipython-sb` gives IPython a private, temporary profile directory: `~/.ipython`, whose startup scripts run outside
  the sandbox, is no longer writable from it
- A reply up to the documented 512 KiB crosses the transport: above 128 KiB it failed with a bare `LineTooLong`
- The source distribution ships only the package and its top-level documents, not the whole repository
- `netifaces`, unused, is no longer a dependency: installing no longer compiles a C extension
- The output a sandboxed function prints is captured on every call, not only the first one of the sandbox
- `python-sb` reads its command line as CPython does: `-mjson.tool`, `-cprint(1)`, `-Im json.tool` and a script
  without the `.py` suffix run, and a `--pysandboxes-config` without its value is a usage error
- `python-sb -m <module>` finds the module's rule file in a fresh interpreter
- A refused extra shutdown no longer makes a later shutdown stop a sandbox still in use
- A missing `bwrap`, `firejail`, `unshare`, `slirp4netns` or `iptables` raises a `SandBoxError` instead of exiting
  the application, and an exception in the sandbox's event loop no longer ends the process
- An application that opens `sandboxes()` many times no longer ends in a `RecursionError` on an import
- A refusal raised through `shutil.rmtree` still names the rule that refused it
- Under a `learn=false` profile, `ipython-sb` adds no private profile directory and runs the standard Python REPL,
  unless the profile names its own with `expose-rw=<dir>` and `env=IPYTHONDIR=<dir>`
- A builtin named by both `eval-call=ALLOW:` and `eval-call=DENY:` (or a `DENY` pattern) is refused to the evaluated
  code: `DENY` already won in the rules, but the name was still handed to the code
- Creating a subinterpreter is a `process-exec` call, denied by default: code run in a new interpreter escaped every
  Python guard, `python-import` alone allowing it
- `os.readlink`, `Path.glob` and `os.scandir` no longer reveal a link target or a name outside the exposed directories
- A hard link to a read-only file, a fifo or a device node in a read-only directory, and removing or moving a link out
  of a read-only directory are refused
- A relative `ignore=` pattern, such as `ignore=.secrets`, also hides the files under a directory of that name
- `Path.glob(case_sensitive=...)` is honoured on Python 3.13 and later, and `os.open` with flags that are not an
  integer raises CPython's `TypeError`
- `sendmsg()` with an address, and `sendto()` on a TCP socket (TCP Fast Open), are checked against the `net=` rules
- An IPv4-mapped IPv6 address (`::ffff:a.b.c.d`) is judged by the IPv4 `net=` rules
- `listen()` on a socket that was never bound needs an IN rule for the wildcard address, like `bind(("", 0))`
- Connecting or sending to a Unix socket needs write access to its path, as the kernel requires
- A connection to a host name is allowed only if every address the name resolves to is allowed, and goes to an
  address that was checked
- An IN rule opens its port at the OS layer as it does in the Python layer; an empty port field allows no port in
  either layer; long port lists and IPv4 DNS servers no longer break the iptables rules
- Learning a `bind(("", port))` no longer crashes rule generation, and pinned name resolution accepts service names
  such as `"http"`
- `os.setresuid`, `os.setresgid`, `os.initgroups`, `os.unshare`, `os.setns`, `threading.settrace_all_threads`,
  `threading.setprofile_all_threads`, `sys.monitoring`, `sys.remote_exec`, `ctypes.wstring_at`, `pickle._loads`,
  `pickle._Unpickler`, `subprocess._fork_exec` and the `multiprocessing.get_context(...).Process` classes are refused
  unless `python-api` allows them; a function-level `ALLOW:subprocess.Popen` now also needs
  `ALLOW:_posixsubprocess.fork_exec`
- `os.readlink`, `os.unlink`, `os.remove`, `os.rename` and `os.replace` with `dir_fd=` judge a link as the path form
  does, on the directory holding it
- A relative `ignore=` pattern no longer hides a whole exposed directory that lies under a directory of that name
- The `ignore=` and `copy_function=` callbacks of `shutil.copytree` run under the file rules
- `--port` on the command line wins over any number of `port=` lines in the profile and its includes
- A connection to an abstract Unix socket is refused with the sandbox's error instead of a `ValueError`
- `python-sb -m <package>` finds the rule file of a namespace package
- A function called from a sub-package finds the rule file of the nearest package that holds one, not only its top
  package's
- `python-sb` exits with `128 + signal` when the script is killed by a signal (137 for `SIGKILL`), as a shell reports
  it
- `sys.exit("message")` in a script run by `python-sb` prints the message and exits with 1, as CPython does
- CPython's test modules (`_testinternalcapi`, `_testcapi`) no longer create a subinterpreter unless `python-api`
  allows it
- The samples no longer compile `netifaces`
- `eval-max-alloc` also bounds `<<` and the width or precision of a format (`%`, f-string, `format`, `str.format`):
  `'%0100000000d' % 1` allocated 100 MB whatever the budget
- An `eval-max-depth` above what the interpreter's stack can walk refuses the source instead of raising
  `RecursionError`
- `delattr` and `hasattr` handed to the evaluated code in a context are graded as strong capabilities, as
  `eval-call` already reported them
- A relative import, and the import of a submodule of a module the sandbox always keeps (such as `asyncio.subprocess`),
  are checked against the `python-import` rules
- Imports from other threads or tasks are no longer let through while the sandbox loads its own modules
- Under `python -O`, the guards are no longer applied twice when the sandbox is activated again
- A dotted `python-import=` rule such as `os.path`, which never matches, logs a warning
- `unenv=` accepts the same `*` patterns as `env=` and removes variables wherever it is written in the profile, and an
  exact `env=` beats a wildcard one whatever their order
- A wildcard `env=*_KEY=value` sets the given value on every matching variable instead of forwarding the host value
- `--port=` on the command line takes precedence over `port=` in the profile
- An include that exists but cannot be read is a configuration error instead of being skipped; a bare-name include
  inside an included file is resolved next to that file, and a profile including itself is loaded once
- The error raised when the Python executable's symlink chain cannot be resolved names the broken path
- Evaluated code can no longer define, import, catch or bind a name starting with `__sb_`, which replaced the guard's
  own helpers and lifted the budgets
- `x *= n`, `x += y` and `x **= n` in evaluated code are bounded by `eval-max-alloc`, like `x * n`
- A worker thread that finally stops no longer counts against `eval-max-leaked-threads`, which refused every later
  evaluation for the life of the process
- Two evaluations starting at once no longer leave the thread guard disabled
- `exec` or `eval` of a code object accepts only one that guarded `compile` produced, whatever its file name, and runs
  it under the budgets and the timeout; a tree from `compile(..., ast.PyCF_ONLY_AST)` compiles again
- On Python 3.13 and later, `exec()` without a namespace no longer rewrites the caller's local variables
- A source nested deeper than the recursion limit is refused by `eval-max-depth` instead of raising `RecursionError`
- `eval-syntax` accepts only AST node names, not `parse` or `NodeVisitor`, nor the deprecated `Num`

### Added
- A profile can raise one of firejail's limits for itself, e.g. `firejail.rlimit-as=600m` for a framework that maps
  more than 300 MB at import
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
  import right is not a call right. A registry of 145 sensitive
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
