# Security assessment of the Python layer — attacks and what stops them

This page is a red-team report on the **Python-level guards** — the dynamic
patching that denies file, socket, import, environment and sensitive-call
access from inside the running interpreter (`guard_files`, `guard_socket`,
`guard_import`, `guard_envs`, `guard_api`, and the arming machinery). It
documents, objective by objective, what hostile code can and cannot reach once
a profile is armed, which layer stops each attempt, and — crucially — the
residual limits the layer does **not** claim to cover.

It is the companion of [the `eval-*` assessment](audit-eval-security.md), which covers
the dynamic-code sub-language, and of [weaknesses](weaknesses.md), which lists
the limits of the package in prose. This page turns those prose limits into a
structured, test-pinned matrix and names the enforcing function or class for
every row. Read [implementation](implementation.md) first if you need to know
*how* the patching works before reasoning about *what it stops*.

The separate [native guard study](audit-native-guard-study.md) evaluates C wrappers and
CPython audit hooks as ways to reduce introspection of original functions. It
records the prototype results and why a general native layer was not pursued.

---

## The threat model — and why it differs from the `eval-*` report

The two reports do **not** share a threat model, and conflating them would be a
false guarantee.

- In the [`eval-*` report](audit-eval-security.md) the attacker controls a **source
  string** evaluated inside a **bounded namespace**. There the report can
  honestly say "every attribute read passes through `_check_attr`": the
  attacker never holds a real object reference the guard did not hand out.

- **Here the attacker controls arbitrary bytecode running in the host
  interpreter.** Any granted callable, any module object, any frame is a live
  Python object with full introspection. [weaknesses.md](weaknesses.md) states
  the consequence plainly: *"arbitrary Python can always call native code …
  the OS-sandboxes remain the real barrier."*

So the useful columns here are **not** "blocked vs allowed" in an absolute
sense. They are: **what the layer costs the attacker**, **what learning mode
makes visible**, and **which OS layer actually stops what the patching cannot**.
The Python layer's job is to deny sensitive operations from *non-hostile* code
and to surface them in learning mode — not to contain hostile bytecode. That is
the OS sandbox's job ([firejail](firejail.md), [bwrap](bwrap.md),
[unshare](unshare.md), [qemu](qemu.md), [landlock](landlock.md)).

### The design target: wayward LLM-generated code

Naming the reader this layer is built for decides what is worth building, so it
is stated here rather than left to be inferred from the matrix.

**The target is code an LLM produced while solving the wrong problem, not an
adversary.** Such code reaches for `open`, `requests.get` or `subprocess` in the
open, and stops at the first refusal. The layer exists to make that refusal
happen, to name the rule that caused it, and to record it in learning mode.

Code written to break out is explicitly **out of scope**, and not for lack of
effort: it needs none of the paths listed in
[section 6](#6-disarm-the-guard-or-reach-an-original). One `ctypes` call, or one
C extension, leaves every Python-level guard untouched and intact. Hardening
this layer against that reader would buy nothing the layer does not already
concede on the line above.

Two consequences, both deliberate:

- **No C extension holding the arming flag, and no PEP 578 audit hook guarding
  it,** are planned. Either would close one row of section 6 while the rows below
  it stay open, and neither survives a reader who can call native code anyway.
  The one audit hook the layer does install, in `guard_import`, is not that: it
  keeps the import finder at the head of `sys.meta_path`. Frameworks put their
  own finder there when they are imported (crewai, wrapt post-import hooks,
  httpx2 aliases, py-key-value), so overtaking the guard is the ordinary case,
  not an attack; the hook moves it back before each import instead of refusing.
- The residual entries in section 6 are **documented, not scheduled**. What the
  layer does owe its target is that an accidental disarming be *loud* rather
  than silent.

---

## Table of contents

- [Two enforcement states: disarmed and armed](#two-enforcement-states-disarmed-and-armed)
- [Attack matrix by objective](#attack-matrix-by-objective)
  - [1. Read or write a file outside the whitelist](#1-read-or-write-a-file-outside-the-whitelist)
  - [2. Open a socket or exfiltrate](#2-open-a-socket-or-exfiltrate)
  - [3. Execute a process or native code](#3-execute-a-process-or-native-code)
  - [4. Read a secret](#4-read-a-secret)
  - [5. Import a forbidden module](#5-import-a-forbidden-module)
  - [6. Disarm the guard or reach an original](#6-disarm-the-guard-or-reach-an-original)
  - [7. Mutate the rules](#7-mutate-the-rules)
  - [8. Attack the IPC channel](#8-attack-the-ipc-channel)
  - [9. Poison learning mode](#9-poison-learning-mode)
- [Guards that are inert by design](#guards-that-are-inert-by-design)
- [Residual limits — denial of service](#residual-limits--denial-of-service)
- [Reproducing the assessment](#reproducing-the-assessment)

Every row is marked **demonstrated** (pinned by an executed test) or
**reasoned** (established from the source, not run as an isolated payload).

---

## Two enforcement states: disarmed and armed

Nothing is enforced until `lifecycle.arm()` flips a module global
(`_armed`, set in `lifecycle.arm()`, read by `lifecycle.is_armed()`).
Framework code runs disarmed; user code runs armed. `lifecycle` is the single
owner of that state: `guard_api` reads it through the `_lc_is_armed` alias (see
[objective 6](#6-disarm-the-guard-or-reach-an-original)), and `guard_socket`'s
`_rules_loaded` flag tracks a different concept.

The wrappers short-circuit when disarmed — `guard_api`'s control point returns
the raw function if `not _lc_is_armed()` (`guard_api._wrap_guarded`). This is by
design, but it also means the arming flag is a single point whose reset
disarms everything; see
[objective 6](#6-disarm-the-guard-or-reach-an-original).

---

## Attack matrix by objective

### 1. Read or write a file outside the whitelist

| Attack | Layer | Status |
|---|---|---|
| Read/write a path outside `expose-ro`/`expose-rw` | decision on the canonical path in `guard_files._apply_dest_to_src_rules`: `startswith` match against each `FSExposeRule` → `raise RulePermissionError` | **Blocked — demonstrated**: `test_guard_escape_fixes.py::test_symlink_leaving_the_exposed_dir_is_denied` asserts the out-of-scope secret resolves to `(None, None)` |
| Symlink inside the scope pointing outside it | decision taken on the `guard_files._safe_realpath`-resolved path, not the raw one | **Blocked — demonstrated** (`test_symlink_leaving_the_exposed_dir_is_denied[absolute,relative]`) |
| Create a symlink whose target is out of scope | `guard_files._wrap_os_symlink` validates the target (`os.symlink` in the guard's patch table) | **Blocked — demonstrated** (`test_creating_a_symlink_out_of_scope_is_refused`) |
| Name the file relative to an open directory (`dir_fd`, `src_dir_fd`, `dst_dir_fd`), so a check against the current directory would see the wrong path | `guard_files._check_dir_fd` resolves the descriptor (`_dir_fd_path`: `/proc/self/fd/<n>` on Linux, `F_GETPATH` on macOS) and applies the rules to the effective path, for `os.open`, metadata and access checks, `symlink`, and one- or two-path operations (`unlink`, `rmdir`, `mkdir`, `rename`, `replace`, `link`); `unlink`, `rmdir` and `mkdir` count as writes. The call keeps its original arguments: no remapping under `dir_fd` | **Blocked — demonstrated** (`test_guard_files_coverage.py::test_a_dir_fd_removal_is_checked_against_the_directory_it_names`, `::test_body_two_filenames_denies_rename_through_a_read_only_dir_fd`, `::test_wrap_os_open_denies_a_write_through_a_read_only_dir_fd`, `::test_wrap_os_open_denies_an_ignored_path_with_dir_fd`, `::test_wrap_os_symlink_denies_a_read_only_dir_fd`; `test_guard_shutil.py::test_shutil_rmtree_cannot_empty_a_read_only_tree`) |
| Pass a `dir_fd` the guard cannot resolve | `_dir_fd_path` denies the call instead of falling back to the current directory | **Blocked — demonstrated** (`test_guard_files_coverage.py::test_dir_fd_path_denies_a_descriptor_it_cannot_resolve`) |
| Rename the directory between the descriptor lookup and the operation | the lookup and the syscall are two separate steps | **Open — reasoned** (time-of-check/time-of-use race, noted in [weaknesses.md](weaknesses.md)); the OS sandbox is the barrier |
| Use a descriptor already held (`open(fd)`, `os.open`, `os.stat`, `os.listdir`, `os.chdir` on an int, or an inherited fd) | an int names no path, so the wrappers pass it through: the call that opened it was checked | **Open by design — demonstrated** (`test_guard_files_coverage.py::test_wrap_filename_passes_through_a_file_descriptor`, `::test_wrap_os_open_passes_through_a_file_descriptor`); a held descriptor is a capability, as a held `dir_fd` is |
| Reach the original `io.open` via its closure cell | wrapper keeps a reference to the original (patch-factory closure) | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_closure` asserts the original is reachable) |

The canonicalization is itself re-entrant-safe: `_safe_realpath` calls
`os.lstat`/`os.readlink`, which are patched, so a `_canonicalizing` context var
suppresses the inner re-check — it is read at the head of
`_apply_dest_to_src_rules`. The path
*returned* to the syscall stays unresolved, so link semantics are preserved;
only the *decision* uses the resolved path.

### 2. Open a socket or exfiltrate

| Attack | Layer | Status |
|---|---|---|
| `connect()`/`bind()` to a host outside `net=` | `guard_socket._check_address` → `_check_address_with_rules` on the patched `socket.socket` | **Blocked — demonstrated** (`test_guard_socket.py::test_connect_enforces_the_rules`, `::test_no_rules_denied_connection`) |
| AF_UNIX socket path exempted from the rules | `_check_unix_socket` applies the file rules to the socket path | **Blocked — demonstrated** (`test_guard_escape_fixes.py::test_unix_socket_out_of_scope_is_denied`) |
| `bind(("", port))` wildcard host slips the rule | `guard_socket._resolve_wildcard_host` rewrites `""` to `0.0.0.0`/`::` before the check | **Blocked — reasoned** |
| `import _socket` and build the C base class directly | `socket.socket` is a Python *subclass* of the C `_socket.socket` and does not redefine `connect`, so patching the subclass alone would leave the base class reachable; the rule replaces the class the C module publishes with a guarded subclass of it (`guard_socket.py`, `_guarded_socket_class`) | **Blocked — demonstrated** (`test_guard_socket_twin.py::test_connect_through_the_c_class_is_refused` refuses the connection under `python-sb`) |
| Resolve a name through `_socket` instead of `socket` | `socket.py` does `from _socket import *`, so `socket.gethostbyname is _socket.gethostbyname` — the `posix` relationship. `getaddrinfo` differs: `socket.py` redefines it, leaving the raw C one a separate unnamed function. Both C names carry the socket wrapper | **Blocked — demonstrated at the table** (`::test_every_guarded_resolution_call_has_its_c_twin`; removing a twin fails it). The end-to-end check compares the two names rather than asserting a refusal: with no resolver the call dies of `gaierror` before the guard is consulted |
| `gethostbyaddr`, `getnameinfo` | shared with `_socket` by the same star-import, but **no rule guards them under either name** | **Open — demonstrated** (absent from `patch_rules`); reverse lookup is not covered by the DNS rules |
| Reach the original class through the type graph (`socket.socket.__mro__[1]`) | none — attribute patching replaces names, not the inheritance chain | **Open — by construction**, same shape as the closure cell in §1. Out of scope for the [wayward-LLM target](#the-design-target-wayward-llm-generated-code) |
| Lower-level fd handoff (`socket.fromfd`, `socketpair`, an fd inherited from the parent) | not in the socket patch table — no `_check_address` on an fd the process already holds. On Windows only, `socket.socketpair` is patched, but to exempt rather than check: see the next row | **Open — reasoned**; contained only by the OS network namespace ([unshare](unshare.md)/[netfilter](dns.md)) |
| Connect to a loopback port from inside `socket.socketpair` on Windows | the stdlib emulates `socketpair` over a loopback listener, so `guard_socket._wrap_socket_socketpair` sets the thread-local `_socketpair_scope.active` for the call, and `_check_address` lets any loopback address through while it is set | **Open — reasoned**: a third switch of the objective 6 class, reachable as a module global; loopback only, Windows only |

### 3. Execute a process or native code

| Attack | Layer | Status |
|---|---|---|
| `os.system`, `os.exec*`, `os.fork`, `subprocess.Popen/run/...` | denied by the sensitive-function registry, independently of import rights: `guard_api.SENSITIVE_API`, wrapped at `guard_api._wrap_guarded`, which raises `RuleApiPermissionError` | **Blocked — demonstrated** (`test_guard_api.py`, `test_guard_os.py`) |
| `subprocess.Popen` / `ctypes.CDLL` patched as classes | patched on `__init__`, not the class object, to keep `isinstance`/subclassing (`guard_api._PATCH_TARGET`) | **Blocked — demonstrated** (`test_guard_api.py::test_class_entry_denies_and_allows_construction`) |
| `ctypes.pythonapi` native calls | it is a `PyDLL` **instance** built at import time — no `__init__` runs, so it is never wrapped (documented in `guard_api`, next to the registry) | **Open — reasoned** (matches [weaknesses.md](weaknesses.md); OS layer's job) |
| Reach an original sensitive function via `__wrapped__` | `_wrap_guarded` decorates with `guard_wraps.guard_wraps`, which drops the back-reference | **Closed** — see [objective 6](#6-disarm-the-guard-or-reach-an-original) for the evidence; the wrapper's closure cell still holds the original |

### 4. Read a secret

| Attack | Layer | Status |
|---|---|---|
| Read an env var outside `env=` | `os.environ` filtered to the whitelist at parse time; learning wrapper `guard_envs.LearnEnviron` | **Blocked — demonstrated** (`test_guard_env.py::test_unknown_variable_leaves_the_key_absent`, `test_learn_environ.py`) |
| Read the parent's env via `/proc/$PPID/environ` | a file read — subject to the file rules (objective 1) if `/proc` is out of scope; **not** otherwise | **Reasoned**; the real barrier is the OS sandbox hiding `/proc` (noted in [weaknesses.md](weaknesses.md)) |
| Read process memory / another module's globals | any function's `__globals__` exposes its module namespace | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_globals_introspection`, xfail-pinned as open) |

### 5. Import a forbidden module

| Attack | Layer | Status |
|---|---|---|
| `import` a module outside `python-import=` | `guard_import.GuardFinder.find_spec` denies via `_is_import_allowed` → `raise RuleModuleNotFoundError`; the finder is inserted at `sys.meta_path[0]` when the rules are activated | **Blocked — demonstrated** (`test_guard_import.py`, `test_guard_escape_fixes.py::test_find_spec_denies_a_module_outside_the_rules`) |
| Unhook the finder from `sys.meta_path`, or insert a finder ahead of it | `sys.meta_path` stays a writable list, but `guard_import._audit_import`, a PEP 578 audit hook installed with the finder, sees the live list on every `import` event and moves the guard finder back to its head (restoring it if it was dropped) before CPython walks it, so the next import is checked and the other finders, reached through `GuardFinder`'s delegation, keep working; a `sys.meta_path` that is no longer a list refuses the import. Python offers no way to remove an audit hook | **Blocked — demonstrated** (`test_escape_pysandbox.py::test_tampering_with_meta_path_leaves_the_next_import_guarded`, `test_a_framework_finder_ahead_of_the_guard_keeps_working`) |
| Empty rule set treated as "no filter" | empty `_rules` is deny-all, wildcard `("*",)` is allow-all (`guard_import._is_import_allowed`) | **Blocked — demonstrated** (`test_no_import_rule_denies_every_module`, `test_wildcard_import_rule_allows_every_module`) |
| Reach a module already in `sys.modules` (e.g. `os`, pre-imported by the framework) | `find_spec` is not consulted for a cached module — but its **sensitive functions** are still denied by objective 3 | **Reasoned**: import rights and call rights are deliberately distinct (`guard_api.py` docstring); a reachable `os` module is not a reachable `os.system` |

### 6. Disarm the guard or reach an original

| Attack | Layer | Status |
|---|---|---|
| Walk `object().__subclasses__()` to the guard modules and reset their state | nothing blocks the class-hierarchy walk | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_subclasses`, xfail-pinned; reaches `guard_import` and sets `_rules=()`) |
| Reset the `_armed` flag through that same walk | `_armed` is a plain module global of `lifecycle`, re-read on every `is_armed()` | **Open — reasoned** (same class as above; [weaknesses.md](weaknesses.md) names it explicitly) |
| Rebind the call-site alias instead of the flag: `guard_api._lc_is_armed = lambda: False` | `guard_api` imports `is_armed` under the name `_lc_is_armed`, binding the function by value, so the alias is a second, independent switch read by every wrapper | **Open — reasoned** |
| Reach the unguarded original through `__wrapped__` | `guard_wraps.guard_wraps()` replaces `functools.wraps` in the five guards: it restores `__signature__`, then drops the back-reference | **Closed** (the guarded callable does not carry `__wrapped__`; `test_guard_escape_fixes.py`) |
| Reach the original through the wrapper's own closure cell (`__closure__[i].cell_contents`) or `gc.get_referents` | a Python wrapper necessarily holds a reference to what it wraps; hiding the name does not hide the object | **Open — by construction** |
| Obfuscated name construction (`getattr(os, "sy" + "stem")`, `chr()` chains, hex-decoded names) | guard_api wraps the function, not the source text, so the check runs at the call however the name was built; a name that reaches no guarded call (`'__sub'+'classes__'`) is the `__subclasses__` row above | **Closed for guarded calls** (`test_escape_pysandbox.py::test_a_name_built_at_run_time_is_refused_at_the_call`) |

These are the defining limits of a patch-based layer, not defects to be fixed
in it. They are why the OS sandbox exists.

### 7. Mutate the rules

| Attack | Layer | Status |
|---|---|---|
| Overwrite a decision dict in place | rules stored in `immutable_dict.ImmutableDict`, a `tuple` subclass with no mutating API; `guard_api._allowed` is one | **Blocked — demonstrated** (`test_immatuable_dict.py`) — for *direct* mutation |
| Rebind the module global that holds the `ImmutableDict` | the binding itself is a plain global, reachable via objective 6 | **Open — reasoned**: immutability protects the container, not the name that points at it |

### 8. Attack the IPC channel

The main process talks to the sandboxed child over SSE on localhost.

| Attack | Layer | Status |
|---|---|---|
| Call the SSE endpoint without the token | Bearer-token check, request refused on mismatch (`remote/sse_server_daemon`) | **Blocked — reasoned** (token is a per-run UUID minted in `python_sb`) |
| Reach the endpoint from another local process | bound to `localhost` with a random free port (`remote/client_subprocess_sse_daemon.find_free_port`) + the token above | **Reasoned**: raises cost; a co-resident process that can read the port and token is not stopped by this layer ([weaknesses.md](weaknesses.md)) |

### 9. Poison learning mode

This objective is **not** in [weaknesses.md](weaknesses.md) and is specific to
the project's design, so it is stated in full.

In learning mode the verified guards do **not** enforce: they record the
attempt and then let the real operation proceed. For example, the sensitive-call wrapper
calls the real function anyway (`guard_api._wrap_guarded`), and the file and
import guards record instead of raising (`guard_files._apply_dest_to_src_rules`,
`guard_import.GuardFinder.find_spec`). Every observed file, socket, import, env
and call is serialized verbatim into the next run's profile
(`learning.generate_config_from_learning`), with **no
validation** of whether the behavior was legitimate.

Consequence: hostile code run under learning mode both **executes unguarded**
and **writes its own permissions into the whitelist** the next run trusts.

| Layer | Status |
|---|---|
| The only barrier is human review: the generated file prints *"Check and update this file to validate the rules"*, and every sample profile warns *"Never use learning mode with untrusted code"* | **Open by design — demonstrated** that rules are written without validation (`test_learning.py::TestGenerateConfigFromLearning`); the safeguard is operational, not enforced by any layer |

---

## Guards that are inert by design

One guard module does nothing today, and one subject — pickle — is covered only
in part, by design. Neither is a discovered vulnerability -- do not report them
as escapes.

- **Pickle deserialization is covered only in part, by design.**
  `pickle.Unpickler` **is** `_pickle.Unpickler`, an immutable C type, so neither
  its `__init__` nor its `load` can be patched. Rebinding the module name to
  a function would break the subclassing a restricted unpickler needs: this is the same
  shape as `ctypes.pythonapi`. `Unpickler(fp).load()` therefore stays reachable,
  pinned as `test_guard_api.py::test_the_unpickler_route_is_guarded` (xfail).

  What *is* covered runs through `guard_api`: `pickle.loads`, `pickle.load` and
  their `_pickle` twins are registry entries under the `deserialization`
  category, denied by default like every other sensitive call and grantable with
  `python-api=ALLOW:deserialization` (warned at load, as `dynamic-code` is). A
  pickle stream is a program: its opcodes name a callable and call it, which
  reaches `os.system` without an import and without a source string the `eval-*`
  layer could parse. Pinned end to end by
  `test_guard_api.py::test_pickle_loads_and_its_twin_are_refused_end_to_end`.

  Like the rest of this layer, that denies the call from cooperative code and
  gives learning-mode visibility. It is not a barrier against hostile bytecode,
  which reaches `os.system` by a hundred other routes; the OS sandbox is the
  barrier for that class. The two pickle escape tests stay `xfail` because they
  exercise the import guard alone, without `guard_api` armed.

  The only untrusted data this package unpickles is the child's result and
  exception payloads, rebuilt in the **trusted parent** by
  `remote/base_sse_daemon._rebuild_remote_exception` and the result branch of the
  same module's event dispatch. A crafted payload would be arbitrary code
  execution in the host process, outside the sandbox. Both child->parent sites
  therefore go through `remote/tools.py::from_b85_restricted`, in two steps.
  First, an opcode prescan (allowlist by family plus anti-DoS budgets). Then, a
  `find_class` that triggers no import from the stream and vets each global:
  - the exception channel is fail-closed (Exception subclasses, `tblib`, base
    data types);
  - the result channel is a fail-open denylist of dangerous gadgets keyed by
    every C-twin (`posix.system`, `_socket.socket`);
  - a shape check runs on `tblib.Traceback` before `as_traceback()`.

  The result guard is toggled by `remote-result-guard` (default on). Being
  fail-open, it raises the cost of a gadget on return values rather than closing
  the class; the exception guard is fail-closed. Because an
  exception's state routinely holds a type that guard refuses (`httpx.Request`,
  a `Path`, an application object), the child also sends a descriptor of the
  exception — class, message, denials, all primitives — and the parent falls back
  to it when the rich form is refused, rather than losing the refusal itself. An
  exception crossing that way arrives without its attributes. The
  transport binds `pickle.dumps`/`pickle.loads` at import so the framework's own
  serialization is not charged to the user's profile, and the registry does
  **not** cover this call. See
  [transport-unpickle-guard.md](transport-unpickle-guard.md). `parent->child`
  (args/kwargs) stays on the raw `from_b85`: there the trust runs the other way.

These match the package's stated position: the Python layer raises cost and adds
visibility; the OS sandbox is the barrier.

---

## Residual limits — denial of service

Exhausting CPU, memory or file descriptors is out of scope for this layer, by
the same reasoning as the [`eval-*` report](audit-eval-security.md): a patch on a
Python function cannot bound native resource use. The OS sandbox (cgroups,
`ulimit`, the VM providers) owns denial of service.

---

## Reproducing the assessment

```bash
# blocked escapes (pinned as passing) + known-open escapes (pinned as xfail)
uv run pytest tests/unit_tests/test_escape_pysandbox.py \
              tests/unit_tests/guard/test_guard_escape_fixes.py -v

# the per-guard enforcement corpus grounding the "blocked" rows
uv run pytest tests/unit_tests/guard/test_guard_api.py \
              tests/unit_tests/guard/test_guard_import.py \
              tests/unit_tests/guard/test_guard_socket.py \
              tests/unit_tests/guard/test_guard_os.py \
              tests/unit_tests/test_learning.py -v

# the dir_fd and descriptor rows of objective 1
uv run pytest tests/unit_tests/guard/test_guard_files_coverage.py \
              tests/unit_tests/guard/test_guard_shutil.py -v -k "dir_fd or descriptor or rmtree"
```

At the time of writing this run reports **21 passed, 3 xfailed** for the escape
files, **211 passed, 4 skipped, 1 xfailed** for the guard corpus and
**16 passed** for the `dir_fd` selection on Linux
(three skips are the Windows-only twins of `test_armed_denies_the_windows_twins`,
one is `test_os_chflags_and_lchflags`). The three `xfail` entries of the escape
files are the open escapes: `test_escape_with_subclasses` (objective 6),
`test_escape_with_globals_introspection` (objective 4), and
`test_escape_with_pickle_blocked` (the pickle entry of
[inert guards](#guards-that-are-inert-by-design): removing `pickle` from
`sys.modules` blocks nothing).

Tampering with `sys.meta_path`, a hostile pickle and a name built at run time
are no longer listed. The import audit hook puts the finder back at the head
once it is unhooked or overtaken, as
`test_tampering_with_meta_path_leaves_the_next_import_guarded` shows. Once
armed, guard_api refuses `pickle.loads` and the call a built name reaches, as
`test_a_hostile_pickle_is_refused_once_armed` and
`test_a_name_built_at_run_time_is_refused_at_the_call` show. The corpus `xfail`
is `test_guard_api.py::test_the_unpickler_route_is_guarded`, which records that
`pickle.Unpickler` is an immutable C type. All are
`strict=True`, so if any is ever closed, the XPASS fails the suite and this page
must change with it.

Bottom line: the Python layer denies every sensitive operation from
cooperative code and pins each denial to a test. Against hostile bytecode, it
only raises cost and provides learning-mode visibility: the class-hierarchy
walk, the wrappers' closure originals, `ctypes.pythonapi`,
`pickle`, and the arming flag remain reachable by design. Containing those is
the OS sandbox's role, stated plainly rather than papered over.

## Recommendations

- Treat the Python layer as a guardrail for code that is wrong, not hostile. Against code written to break out, use a kernel provider.
- Never use learning mode with untrusted code: it executes unguarded and writes its own permissions into the whitelist.
- Review every generated profile before trusting it. That review is the only barrier.
- Grant `python-api=ALLOW:deserialization` only when a trusted payload requires it.
- Leave `remote-result-guard` on, and rely on the OS sandbox for denial of service.

## References

- [Security assessment of the `eval-*` guard](audit-eval-security.md)
- [Transport unpickle guard](transport-unpickle-guard.md), [weaknesses](weaknesses.md), [implementation](implementation.md)
- Kernel providers: [landlock](landlock.md), [bwrap](bwrap.md), [firejail](firejail.md), [unshare](unshare.md), [qemu](qemu.md)
