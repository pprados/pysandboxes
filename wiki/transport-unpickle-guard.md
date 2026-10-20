# Parent-side pickle handling on the remote transport

This page describes the current child-to-parent result and exception deserialization paths. It is based on the implementation and tests linked below. It does not treat earlier audit prose as evidence.

## Scope and trust direction

PySandboxes executes a sandboxed call in a child process and returns results over the local SSE transport. The child controls the bytes it sends. A pickle stream can invoke reconstruction callables, so deserializing a child payload in the trusted parent is security-sensitive.

There are two directions in the transport:

- Parent-to-child call arguments use raw `from_b85` in [`sse_server_daemon.py`](../pysandboxes/remote/sse_server_daemon.py). That payload is produced by the trusted parent.
- Child-to-parent results and exceptions use `from_b85_restricted` in [`base_sse_daemon.py`](../pysandboxes/remote/base_sse_daemon.py). The raw [`from_b85`](../pysandboxes/remote/tools.py) function is not the effective decoder for those response values.

The child serializes values with `to_b85`. It no longer reloads and compares the value before sending: that would not establish that the parent can safely reconstruct attacker-controlled bytes. The parent-side checks are applied when it receives the response.

The exception sender emits both a rich pickle of `(exception, traceback)` and a primitive descriptor plus traceback. The parent tries the rich form first and uses the descriptor when restricted loading refuses it. See [`sse_server_daemon.py`](../pysandboxes/remote/sse_server_daemon.py) and [`base_sse_daemon.py`](../pysandboxes/remote/base_sse_daemon.py).

## What the restricted loader checks

[`from_b85_restricted`](../pysandboxes/remote/tools.py) base85-decodes the payload, prescans the pickle stream, then loads it with a restricted unpickler and a channel-specific predicate.

### Opcode and size prescan

The prescan uses `pickletools.genops` to reject opcodes outside the protocol-5 allowlist and enforce byte, opcode-count, memo-entry, and MARK-depth budgets. In particular, the allowlist excludes extension opcodes and protocol-0 global forms that could avoid the `find_class` check. The prescan does not execute pickle reconstruction code.

The scanner deliberately does not emulate the pickle stack to predict every `(module, name)` pair. Memo indirection makes a partial stack interpreter a second implementation that could disagree with the actual unpickler. Instead, allowed `STACK_GLOBAL` references are checked by `find_class` during loading. The test `test_memo_indirection_refused` exercises a memoized `os.system` reference and confirms that the result predicate refuses it: [`test_restricted_unpickle.py`](../tests/unit_tests/remote/test_restricted_unpickle.py).

The HTTP reader also limits an SSE line. `check_sse_line` checks the assembled line on the child before it is sent, while `_MAX_BYTES` bounds the encoded pickle portion on the parent-side loader. The constants and rationale are in [`tools.py`](../pysandboxes/remote/tools.py); the unit tests cover their relationship to the aiohttp reader. These limits reduce oversized-payload and parser exhaustion risks; they do not make an accepted pickle inert.

### Global resolution

The restricted unpickler only resolves a module already present in the parent's `sys.modules`; it does not import a module named by the stream. It resolves dotted names by attribute lookup, then applies the channel predicate. For dotted names it requires the resolved target to be a class, preventing a dotted path from selecting a callable such as a method.

This is a restriction on global lookup, not a guarantee that every admitted class is safe to reconstruct. Pickle reconstruction may invoke methods on an admitted class, which is particularly important for the exception channel below.

## Result channel

Two result modes are implemented:

- `remote-result-mode=data-only` uses a closed set of supported value classes and validates that the reconstructed graph contains only supported exact container/value types. This is the narrower result profile. It is separate from exception handling.
- `remote-result-mode=objects` allows application and library classes, subject to a denylist of known dangerous module roots and builtins. The denylist is intentionally fail-open: a dangerous gadget from an unlisted module may pass. The code lists the roots it currently covers in [`tools.py`](../pysandboxes/remote/tools.py); it does not establish coverage of every alias, C twin, or future gadget.

Python 3.11.5 is the oldest supported version for a reason that lives here. Before it, an enum member pickles as
`getattr(Class, 'NAME')`, a call the restricted unpickler refuses in both modes (`data-only` answers `getattr` for the
`ZoneInfo` constructor only), so a sandboxed function returning an enum member, or an object holding one, failed on its way
back. From 3.11.5 an enum member pickles by a reduce call on its class, which the unpickler accepts.

`remote-result-guard=false` disables the result denylist in objects mode. The opcode prescan and its budgets still run, but globals then load through the standard pickle loader. This setting therefore removes the name-level gadget check; it must not be described as retaining equivalent protection against reconstruction gadgets.

Tests for value mode, object mode, memo handling, and the switch are in [`test_restricted_unpickle.py`](../tests/unit_tests/remote/test_restricted_unpickle.py). They exercise selected cases; they are not a proof that the fail-open denylist is exhaustive.

## Exception channel: residual parent-code-execution risk

The exception predicate accepts any class that is a subclass of `Exception`, along with `tblib` types and a small set of base data classes. It excludes `BaseException`-only classes such as `SystemExit` and `KeyboardInterrupt`, but it does not distinguish trusted exception classes from arbitrary application-defined exception classes. See `exception_predicate` in [`tools.py`](../pysandboxes/remote/tools.py).

This means the rich form can execute reconstruction hooks in the parent. If a matching custom exception class is already imported in the parent, a hostile child payload can select that class and trigger its pickle reconstruction behavior, including a custom `__setstate__`. This was reproduced at the restricted-loader level with a preloaded custom exception class. The probe demonstrates the hook execution, not a complete remote exploit over the SSE socket; the prerequisite remains that the relevant class is present in the trusted parent's process.

The descriptor fallback has a related, independently source-established risk. After resolving the descriptor's module and qualified name from `sys.modules`, `rebuild_from_descriptor` calls `cls.__new__(cls)` for any resolved `Exception` subclass. A custom `__new__` therefore runs in the parent. This was reproduced directly at the descriptor rebuild helper with a preloaded custom exception class. The descriptor's primitive shape check prevents arbitrary pickle globals in that fallback payload, but it does not make the subsequent class constructor inert.

Accordingly, the exception path is **not fail-closed against code execution by reconstruction hooks on preloaded exception classes**. The descriptor fallback preserves the class/message/denials in ordinary cases but is not a safe boundary against a hostile child when such a class is available. The source and direct probes establish the behavior; they do not establish that every application has a reachable malicious exception class.

When the class cannot be resolved, or is not an `Exception` subclass, the code falls back to `SandBoxProtocolError`. A fallback descriptor carries the exception module, qualified name, string message and denial strings; it does not preserve arbitrary exception attributes. `__cause__` and `__context__` are not transported as part of this descriptor. Existing tests cover shape validation and ordinary fallback behavior, but do not assert that hostile `__new__` or `__setstate__` hooks are prevented: see [`test_restricted_unpickle.py`](../tests/unit_tests/remote/test_restricted_unpickle.py).

## Protocol and compatibility details

The regular `to_b85` path pins `_PICKLE_PROTOCOL` to 5. The exception serialization code currently uses `pickle.HIGHEST_PROTOCOL` in [`sse_server_daemon.py`](../pysandboxes/remote/sse_server_daemon.py), rather than that constant. CPython 3.11 through 3.14 currently use protocol 5, but “the fixed protocol constant is used at both ends” is not an implementation invariant. Revisit this if the supported interpreter range or pickle protocol changes.

The opcode allowlist and name resolution depend on CPython behavior. The repository marks compatibility-sensitive sites with `CPYTHON-COMPAT`; review them when adding a Python version. The supported Python range is recorded in project metadata and CI configuration.

## Related API-guard limitation

The xfail for `pickle.Unpickler(...).load()` is in [`test_guard_api.py`](../tests/unit_tests/guard/test_guard_api.py), not in the transport restricted-unpickler tests. It documents a separate Python API guard limitation: the immutable C `pickle.Unpickler` type cannot be patched in the same manner as `pickle.loads`. It should not be read as evidence that the parent-side restricted transport loader is unguarded; nor does it resolve the exception-hook issue described above.

## Security interpretation

- The parent-side result loader has meaningful opcode, size, global-resolution, and channel-predicate checks. `data-only` is narrower than `objects`; the objects-mode denylist is fail-open and not exhaustive.
- The child-to-parent exception loader admits arbitrary preloaded `Exception` subclasses, whose pickle hooks can execute in the parent. The descriptor fallback also invokes a resolved exception class's `__new__`.
- The parent-to-child raw `from_b85` path has the opposite trust direction and should not be confused with child response handling.
- These checks do not replace process isolation. For the broader current threat model and other residual weaknesses, see [`weaknesses.md`](weaknesses.md).
