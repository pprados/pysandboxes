<!-- Copyright (c) 2026, Carbon-It, Philippe Prados (pprados) -->
<!-- License: Apache V2 -->

# Native guard study and decision

This page records the design study of a C extension intended to make the original functions behind PySandboxes' Python guards harder to recover or call through ordinary Python introspection. The study concluded that the technique works for a narrow set of CPython C functions, but does not provide enough coverage to justify a general native guard layer. **The general implementation is abandoned.** The Python guards and `OS_SANDBOX` are the protection in place.

For the threat model and current limitations, see [Weaknesses](weaknesses.md) and the [security assessment of the Python layer](audit-python-security.md). The `eval-*` sub-language has a different threat model; see its [security assessment](audit-eval-security.md). The OS boundary and provider differences are described in [Choosing a provider](os-providers.md).

## What the prototype established

A disposable C extension extracted a CPython builtin's function pointer, retained it in C storage, and invoked it through a native wrapper. The tested `math.sqrt` original was not found by the tested Python heap/profile introspection routes. A single `abi3` binary compiled against Python 3.11 headers also dispatched representative C functions using six call conventions on CPython 3.11, 3.12, 3.13, and 3.14. On 3.12–3.14, `sys.monitoring` observed the public wrapper call but not the direct C-pointer call to `math.sqrt`.

These are positive but narrow results. They establish that a C wrapper can hide a selected C function object from the tested Python routes while preserving its call result. They do not establish equivalent behavior for every function in the registry, every compiler or platform, or every callable kind. The prototype was not a production guard and did not prove thread, reload, subinterpreter, or free-threaded safety.

The study also tested native audit hooks and GC wrappers on Python 3.11 through 3.14. A native hook ran before later Python hooks, and native GC wrappers could deny direct and re-entrant access through saved aliases. However, an existing Python audit hook could silently veto `PySys_AddAuditHook()` even when it reported success. The prototype detected this only by emitting a unique verification event and checking that the native callback observed it. Any production use would have to fail closed when that self-test failed.

## Why the general approach was abandoned

`SENSITIVE_API` holds 121 names. On a Linux host running CPython 3.14, 107 resolve: 77 to built-in/C callables, 28 to Python functions, and two to classes. The other 14 are platform- or version-specific and do not resolve there. Across the other patch tables there are 114 API entries, 63 filesystem entries, 11 socket entries, four eval entries, and four learning-mode environment entries. These are patch entries rather than unique implementations, and aliases overlap.

The pointer technique applies to selected C callables. It does not make Python functions secret: retaining a Python function in C still leaves it visible through Python references, and an exception traceback exposes its frame, code, and globals. Reconstructing a function from that code and globals reproduces the callable. Compiling Python code or shipping bytecode does not remove these objects or provide a secrecy boundary.

Other limits lie outside the technique:

- `object.__subclasses__()` is an operation on immutable built-in types. It cannot be replaced by assigning a Python wrapper and emits no audit event. Native code cannot disable it without changing CPython itself.
- A native audit hook only sees the event CPython emits. It cannot reliably infer which public API caused a shared event: `os.popen()` and `subprocess.run()` can both emit `subprocess.Popen`. Such a hook cannot preserve distinct per-function rules for old aliases in that case.
- Audit events do not carry all arguments needed to reproduce every guard decision. For example, the tested `os.open(..., dir_fd=...)` call emitted `open(path, mode, flags)` without the directory descriptor. Filesystem rules also need canonicalization, symlink handling, and learning behavior.
- Immutable classes can still be found through the type graph. An audit hook can guard selected operations that emit complete pre-effect events, but it cannot guarantee coverage of every method or every path that uses an already-held descriptor or object.
- The `PySys_AddAuditHook()` declaration is unavailable through the Limited API headers used for `abi3`. Requiring it means building a CPython-minor-specific wheel for each supported Python minor and each OS/architecture target. It also adds permanent process-wide state, installation checks, worker lifecycle requirements, and compatibility work for debugging, profiling, learning, and reload.
- Porting all current behavior to C would be a broad rewrite. It would need to preserve filesystem path semantics, `dir_fd`, sockets, platform-specific calls, return values, learning rules, and public Python behavior. That cost is disproportionate to the protection gained while Python functions and interpreter-level introspection remain outside the native pointer technique.

The official [CPython audit-event table](https://docs.python.org/3/library/audit_events.html) is useful for building an event inventory, but its events do not provide complete, one-to-one mediation for these guards. CPython's [audit-hook guidance](https://docs.python.org/3/library/sys.html#sys.addaudithook) explicitly says audit hooks are not a sandbox. These facts rule out treating the hook as a replacement for either the existing guard behavior or the OS boundary.

## Decision

Do not implement a general native guard layer. The prototype has a real, measurable effect for selected C callables, but the full layer would be complicated to build and maintain across Python versions and platforms while leaving important introspection paths open. For the current goal, that is not a sufficient return on the cost.

The study does **not** recommend removing `OS_SANDBOX`. The kernel-backed providers remain the boundary for hostile code. The `none` and `subprocess` providers do not supply that OS boundary and must not be described as equivalent containment. Native wrappers would not change that fact.

The following smaller measures are worthwhile independently of the abandoned native guard:

- Remove generic FFI use from worker startup where practical, including the `ctypes` path used for parent-death signaling and Landlock operations. Verify reachability in a fresh worker; removing `ctypes` from `sys.modules` alone is insufficient.
- Release bootstrap module snapshots and other references that keep pre-activation modules or loaders reachable from user code.
- Keep the direct GC, frame, reload, and import guards documented as reductions of ordinary access paths, not complete prevention of Python introspection.
- Use `OS_SANDBOX` and its provider-specific tests for confinement.

These actions reduce reachable capabilities or make existing guard limitations clearer. They do not turn same-process Python patching into a security boundary.

## References

- [Weaknesses](weaknesses.md) — known limits of Python patching, `ctypes`, and OS providers.
- [Security assessment of the Python layer](audit-python-security.md) — attack paths and their current controls.
- [Security assessment of the eval-* guard](audit-eval-security.md) — bounded source-string execution and its separate threat model.
- [Choosing a provider](os-providers.md) — which providers supply an OS-level boundary.
- [CPython audit events](https://docs.python.org/3/library/audit_events.html) and [audit-hook guidance](https://docs.python.org/3/library/sys.html#sys.addaudithook).
