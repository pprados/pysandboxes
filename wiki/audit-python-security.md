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
structured, test-pinned matrix and adds the enforcement point (`file:line`) for
every row. Read [implementation](implementation.md) first if you need to know
*how* the patching works before reasoning about *what it stops*.

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

Nothing is enforced until `guard_api.arm()` flips a module global
(`guard_api.py:356`, set in `arm()` at `guard_api.py:404`, read by
`is_armed()` at `guard_api.py:417`). Framework code runs disarmed; user code
runs armed. `guard_socket` keeps its own `_armed` flag (`guard_socket.py:189`),
checked in `_check_address` (`guard_socket.py:1021`).

The wrappers short-circuit when disarmed — `guard_api`'s control point returns
the raw function if `not _armed` (`guard_api.py:473`). This is by design, but it
also means the arming flag is a single point whose reset disarms everything;
see [objective 6](#6-disarm-the-guard-or-reach-an-original).

---

## Attack matrix by objective

### 1. Read or write a file outside the whitelist

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| Read/write a path outside `expose-ro`/`expose-rw` | decision on the canonical path in `_apply_dest_to_src_rules`, `guard_files.py:490` → `startswith` match `:496` → `raise RulePermissionError` `:505` | **Blocked — demonstrated**: `test_guard_escape_fixes.py::test_symlink_leaving_the_exposed_dir_is_denied` asserts the out-of-scope secret resolves to `(None, None)` |
| Symlink inside the scope pointing outside it | decision taken on `_safe_realpath`-resolved path, not the raw one (`guard_files.py:487-490`) | **Blocked — demonstrated** (`test_symlink_leaving_the_exposed_dir_is_denied[absolute,relative]`) |
| Create a symlink whose target is out of scope | `_wrap_os_symlink` validates the target (`guard_files.py`, `os.symlink` in the patch table `:1468`) | **Blocked — demonstrated** (`test_creating_a_symlink_out_of_scope_is_refused`) |
| Reach the original `io.open` via its closure cell | wrapper keeps a reference to the original (patch-factory closure) | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_closure` asserts the original is reachable) |

The canonicalization is itself re-entrant-safe: `_safe_realpath` calls
`os.lstat`/`os.readlink`, which are patched, so a `_canonicalizing` context var
suppresses the inner re-check (`guard_files.py:145`, guard at `:477`). The path
*returned* to the syscall stays unresolved, so link semantics are preserved;
only the *decision* uses the resolved path.

### 2. Open a socket or exfiltrate

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| `connect()`/`bind()` to a host outside `net=` | `_check_address` → `_check_address_with_rules` on the patched `socket.socket` (`guard_socket.py:1021-1023`) | **Blocked — demonstrated** (`test_guard_socket.py::test_connect_enforces_the_rules`, `::test_no_rules_denied_connection`) |
| AF_UNIX socket path exempted from the rules | `_check_unix_socket` applies the file rules to the socket path | **Blocked — demonstrated** (`test_guard_escape_fixes.py::test_unix_socket_out_of_scope_is_denied`) |
| `bind(("", port))` wildcard host slips the rule | `_resolve_wildcard_host` rewrites `""` to `0.0.0.0`/`::` before the check (`guard_socket.py:1007`) | **Blocked — reasoned** |
| Lower-level fd handoff (`socket.fromfd`, `socketpair`, an fd inherited from the parent) | not in the socket patch table — no `_check_address` on an fd the process already holds | **Open — reasoned**; contained only by the OS network namespace ([unshare](unshare.md)/[netfilter](dns.md)) |

### 3. Execute a process or native code

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| `os.system`, `os.exec*`, `os.fork`, `subprocess.Popen/run/...` | denied by the sensitive-function registry, independently of import rights: `SENSITIVE_API` (`guard_api.py:26`), wrapped at `_wrap_guarded` (`guard_api.py:466`), `raise RuleApiPermissionError` (`guard_api.py:480`) | **Blocked — demonstrated** (`test_guard_api.py`, `test_guard_os.py`) |
| `subprocess.Popen` / `ctypes.CDLL` patched as classes | patched on `__init__`, not the class object, to keep `isinstance`/subclassing (`_PATCH_TARGET`, `guard_api.py:497`) | **Blocked — demonstrated** (`test_guard_api.py::test_class_entry_denies_and_allows_construction`) |
| `ctypes.pythonapi` native calls | it is a `PyDLL` **instance** built at import time — no `__init__` runs, so it is never wrapped (documented at `guard_api.py:494`) | **Open — reasoned** (matches [weaknesses.md](weaknesses.md); OS layer's job) |
| Reach an original sensitive function via `__wrapped__` | `_wrap_guarded` uses `functools.wraps` (`guard_api.py:471`), which sets `__wrapped__` to the original | **Open — demonstrated**: the project's own test helper reaches the original this way — `getattr(os.symlink, "__wrapped__", os.symlink)` (`test_guard_escape_fixes.py:62`) |

### 4. Read a secret

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| Read an env var outside `env=` | `os.environ` filtered to the whitelist at parse time; learning wrapper `LearnEnviron` (`guard_envs.py:133`) | **Blocked — demonstrated** (`test_guard_env.py::test_unknown_variable_leaves_the_key_absent`, `test_learn_environ.py`) |
| Read the parent's env via `/proc/$PPID/environ` | a file read — subject to the file rules (objective 1) if `/proc` is out of scope; **not** otherwise | **Reasoned**; the real barrier is the OS sandbox hiding `/proc` (noted in [weaknesses.md](weaknesses.md)) |
| Read process memory / another module's globals | any function's `__globals__` exposes its module namespace | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_globals_introspection`, xfail-pinned as still open) |

### 5. Import a forbidden module

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| `import` a module outside `python-import=` | `GuardFinder.find_spec` denies via `_is_import_allowed` → `raise RuleModuleNotFoundError` (`guard_import.py:445-462`); finder inserted at `sys.meta_path[0]` (`guard_import.py:524`) | **Blocked — demonstrated** (`test_guard_import.py`, `test_guard_escape_fixes.py::test_find_spec_denies_a_module_outside_the_rules`) |
| Empty rule set treated as "no filter" | empty `_rules` is deny-all, wildcard `("*",)` is allow-all (`_is_import_allowed`, `guard_import.py:129`) | **Blocked — demonstrated** (`test_no_import_rule_denies_every_module`, `test_wildcard_import_rule_allows_every_module`) |
| Reach a module already in `sys.modules` (e.g. `os`, pre-imported by the framework) | `find_spec` is not consulted for a cached module — but its **sensitive functions** are still denied by objective 3 | **Reasoned**: import rights and call rights are deliberately distinct (`guard_api.py` docstring); a reachable `os` module is not a reachable `os.system` |
| Remove `GuardFinder` from `sys.meta_path` | nothing guards `sys.meta_path` (`guard_self` is inert, below) | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_meta_path`, xfail-pinned) |

### 6. Disarm the guard or reach an original

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| Walk `object().__subclasses__()` to the guard modules and reset their state | nothing blocks the class-hierarchy walk | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_subclasses`, xfail-pinned; reaches `guard_import` and sets `_rules=()`) |
| Reset the `_armed` flag through that same walk | `_armed` is a plain module global (`guard_api.py:356`) | **Open — reasoned** (same class as above; [weaknesses.md](weaknesses.md) names it explicitly) |
| Obfuscated name construction (`'__sub'+'classes__'`, `chr()` chains, hex-decoded `__import__`) | static name scanning is a courtesy, not a barrier — runtime-built names are never seen | **Open — demonstrated** (`test_escape_pysandbox.py::test_escape_with_obfuscated_strings`) |

These are the defining limits of a patch-based layer, not defects to be fixed
in it. They are why the OS sandbox exists.

### 7. Mutate the rules

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| Overwrite a decision dict in place | rules stored in `ImmutableDict`, a `tuple` subclass with no mutating API (`immutable_dict.py:44`); `_allowed` is one (`guard_api.py:355`) | **Blocked — demonstrated** (`test_immatuable_dict.py`) — for *direct* mutation |
| Rebind the module global that holds the `ImmutableDict` | the binding itself is a plain global, reachable via objective 6 | **Open — reasoned**: immutability protects the container, not the name that points at it |

### 8. Attack the IPC channel

The main process talks to the sandboxed child over SSE on localhost.

| Attack | Layer (`file:line`) | Status |
|---|---|---|
| Call the SSE endpoint without the token | Bearer-token check, request refused on mismatch (`remote/sse_server_daemon.py:211`) | **Blocked — reasoned** (token is a per-run UUID; `python_sb.py:114`) |
| Reach the endpoint from another local process | bound to `localhost` with a random free port (`find_free_port`, e.g. `unshare_sse_daemon.py:535`) + the token above | **Reasoned**: raises cost; a co-resident process that can read the port and token is not stopped by this layer ([weaknesses.md](weaknesses.md)) |

### 9. Poison learning mode

This objective is **not** in [weaknesses.md](weaknesses.md) and is specific to
the project's design, so it is stated in full.

In learning mode the verified guards do **not** enforce: they record the
attempt and then let the real operation proceed — the sensitive-call wrapper
calls the real function anyway (`guard_api.py:473-478`), and the file and
import guards record instead of raising (`guard_files.py:498-505`,
`guard_import.py:445-447`). Every observed file, socket, import, env and call is
serialized verbatim into the next run's profile
(`learning.generate_config_from_learning`, `learning.py:38`), with **no
validation** of whether the behavior was legitimate.

Consequence: hostile code run under learning mode both **executes unguarded**
and **writes its own permissions into the whitelist** the next run trusts.

| Layer (`file:line`) | Status |
|---|---|
| The only barrier is human review: the generated file prints *"Check and update this file to validate the rules"* (`learning.py:179`), and every sample profile warns *"Never use learning mode with untrusted code"* | **Open by design — demonstrated** that rules are written without validation (`test_learning.py::TestGenerateConfigFromLearning`); the safeguard is operational, not enforced by any layer |

---

## Guards that are inert by design

Two guard modules exist but do nothing today. This is a deliberate state, not a
discovered vulnerability — do not report them as escapes, and do not "fix" them.

- **`guard_self`** — `patch_rules()` returns `{}` and `activate_guard()` is
  `pass` (`guard_self.py:70-73`). The `GuardModule` scaffolding meant to protect
  `sys.meta_path`/`sys.modules` is present but unwired
  (`_global_patch_in_sys_module` returns the module unchanged, `guard_self.py:64`,
  with a `TODO`). This is why objective 5's `sys.meta_path` removal and
  objective 6's `__subclasses__` walk stay open.
- **`guard_pickle`** — never referenced in `py_sandbox.activate_sandboxes`
  (the wired set is env/file/socket/import/self/api/eval, `py_sandbox.py:353-368`).
  `pickle.loads` therefore runs its opcodes unguarded. Pinned as
  `test_escape_pysandbox.py::test_escape_with_pickle_allowed` (xfail) and
  `::test_escape_with_pickle_blocked` (xfail — removal from `sys.modules` does
  **not** help, because `_pickle` keeps its own C references).

Both match the package's stated position: the Python layer raises cost and adds
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
```

At the time of writing this run reports **14 passed, 6 xfailed** for the escape
files and **219 passed, 1 skipped** for the guard corpus. The six `xfail`
entries are the open escapes in objectives 5, 6 and the pickle row; they are
`strict=True`, so if any is ever closed, the XPASS fails the suite and this page
must change with it.

Bottom line: the Python layer denies every sensitive operation from
cooperative code and pins each denial to a test; against hostile bytecode it
raises cost and provides learning-mode visibility, while the class-hierarchy
walk, `__wrapped__`/closure originals, `sys.meta_path`, `ctypes.pythonapi`,
`pickle`, and the arming flag remain reachable by design. Containing those is
the OS sandbox's role, stated plainly rather than papered over.
