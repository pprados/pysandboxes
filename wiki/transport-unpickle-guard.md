# The transport unpickle guard

PySandboxes runs untrusted code in a child process and talks to it from the
trusted parent over a local Server-Sent-Events transport. Objects cross that
transport as pickle, base85-encoded (`to_b85` / `from_b85` in
`pysandboxes/remote/tools.py`). This page describes the guard that protects the
**parent** when it deserializes what the **child** sent back.

## Why the return channel is dangerous

The whole point of the sandbox is that the code running in the child is not
trusted. Every guard (`guard_api`, `guard_import`, `guard_socket`, ...) runs
**inside the child** to contain it. The return channel does the opposite: it
takes bytes the child produced and reconstructs them **in the parent**, where no
guard runs.

`pickle.loads` is not a data decoder. A pickle stream is a small program, and
deserializing it can call arbitrary callables. So a child that cannot call
`os.system` inside the sandbox (the API guard denies it there) can still return
an object whose reconstruction calls `os.system` **in the parent**:

```python
class Evil:
    def __reduce__(self):
        import os
        return (os.system, ("...",))
```

`to_b85` runs in the child, so the child chooses what `__reduce__` emits. The
parent's `from_b85` would then execute it. This is a sandbox escape through the
one channel that legitimately crosses the boundary.

It does not even need a hand-written hostile module. Benign child code that runs
`eval` (or any deserializer) on untrusted input is enough: the untrusted input
forges the object, the benign code returns it, and the parent executes it.

This guard therefore assumes nothing about the *shape* of what the child sends.
The only reliable defense is what the parent accepts **when it reads** — the
round-trip check in `to_b85` is not a defense, because it runs on the child's
side where the attacker already controls both ends.

## The two channels

Two sites read child-produced payloads, both in `base_sse_daemon.py`:

- the **result channel** — the return value of the sandboxed function;
- the **exception channel** — the `(exception, traceback)` pair raised inside
  the child.

Both go through `from_b85_restricted`. The reverse direction (the parent sending
arguments and keyword arguments to the child) stays on the raw `from_b85`: there
the trust runs the other way and it is out of scope.

## The layers

`from_b85_restricted` applies several independent checks. They do disjoint work;
none is sufficient on its own.

### 1. Opcode prescan

Before anything executes, the stream is walked with `pickletools.genops`, which
parses without running it (no `__reduce__` is called). Two checks:

- an **allowlist of opcodes**, enumerated by family (all integer variants, all
  string variants, and so on) rather than by observation. Anything outside it is
  refused. This removes the opcodes that bypass the class check below: the
  extension opcodes (`EXT1`/`EXT2`/`EXT4`, which resolve through the `copyreg`
  extension cache and can skip `find_class` when that cache is warm), the
  protocol-0 `GLOBAL`/`INST`/`OBJ` forms, and persistent-id opcodes;
- **anti-DoS budgets**: a cap on the number of opcodes, the number of memo
  entries, the byte size, and the `MARK` nesting depth. A memo bomb passes the
  class check but is caught here.

#### The byte budget, and the ceiling that really applies

The byte budget is not a free choice. The payload travels as a single SSE line,
and aiohttp refuses a line longer than `8 * ClientSession(read_bufsize=...)` —
512 KiB on the default buffer. Measured end to end: a line of 524240 bytes
crosses, 524242 raises `aiohttp.http_exceptions.LineTooLong`.

That reader is the ceiling, and it applies **before** this prescan: the refusal
happens while the response is being read, so an oversized result never reaches
the guard at all. The child therefore checks the assembled line itself, before
sending it (`check_sse_line`), and the caller gets a refusal naming the size and
the limit instead of a `LineTooLong` naming nothing. The whole line is measured,
since the reply also carries the exception forms and whatever the sandboxed
function printed, all sharing one budget.

The budget is derived from that ceiling rather than chosen:

```
line    <= 8 * read_bufsize                = 524288
line     = b85(pickle) + envelope + stdout/stderr
b85(n)   = ceil(n / 4) * 5                 = 1.25 * n
n       <= (524288 - envelope) / 1.25      = 419392 with no captured output
```

`_MAX_BYTES` is 384 KiB, which encodes to 491520 bytes and leaves 32 KiB of the
line for the JSON envelope and for whatever the sandboxed function printed. It
previously read 128 MiB, two orders of magnitude above anything the transport
can carry, which made it a number that described nothing.

A unit test pins `_SSE_LINE_LIMIT` against aiohttp's own default, so raising the
buffer on the `ClientSession` — the only way to lift the ceiling — reddens CI
instead of leaving the two sides silently inconsistent.

The prescan deliberately does **not** try to inventory the `(module, name)`
pairs the stream references. Under memo/`BINGET` indirection a stack-simulating
scan diverges from what the C unpickler actually resolves (it would see a memo
reference where the unpickler resolves `os.system`). Reproducing the match would
mean reimplementing the pickle stack — a second interpreter, whose divergence is
itself a bypass class. Names are left to `find_class`, during the load.

### 2. `find_class`, common rules

- **No import is triggered by the stream.** A module that is not already loaded
  in the parent is refused rather than imported, so the stream cannot run a
  module's import-time code. Note this does not, by itself, block `os`/`posix`:
  they are almost always already loaded. What blocks them is the per-channel
  predicate.
- The dotted qualified name (protocol 4+ carries `Outer.Inner`) is resolved
  in-house by successive `getattr`, not through `pickle._getattribute`, which is
  private and whose signature and return value have changed across CPython
  versions.

### 3. The result channel: a fail-open denylist

The result is the return value of the sandboxed function, so it can legitimately
be almost anything: base types, application classes, third-party library types
(`numpy`, `pandas`), common standard-library types (`pathlib.Path`, `uuid.UUID`,
`collections.OrderedDict`). Requiring an allowlist here would break real return
values, so the result channel refuses only a **denylist of dangerous gadgets**
and lets everything else through.

The denylist is keyed by capability and, critically, by every alias and C-twin
that can appear as `__module__` in a stream. `os.system` does not arrive as
`os.system` — it arrives as `posix.system` on Linux, `nt.system` on Windows;
`socket.socket` can arrive as `_socket.socket`. A denylist written against
import names would miss the very gadget it is meant to stop. It covers OS
execution (`posix`/`nt`/`os`, `subprocess`, `pty`), imports (`sys`, `importlib`,
`runpy`), networking (`socket`/`_socket`), low-level access (`ctypes`,
`_thread`, `mmap`), callback gadgets (`operator`, `functools`), and the
dangerous builtins (`eval`, `exec`, `compile`, `__import__`, `__build_class__`,
`getattr`, `type`, ...).

This layer is **fail-open by nature**: a module not on the list passes. That is
a deliberate trade-off. Making it fail-closed would break legitimate results, so
the design accepts that a determined attacker reaching for an unlisted gadget can
get through, in exchange for never rejecting an honest return value. The threat
it actually stops is the common one: `eval`/deserialization producing an obvious
gadget. It is defense in depth, not a closure.

### 4. The exception channel: fail-closed

The exception payload is always an `Exception` instance plus a `tblib.Traceback`.
The predicate accepts an `Exception` subclass (keying on `Exception`, not
`BaseException`, which keeps `SystemExit`/`KeyboardInterrupt` out of the gadget
set), `tblib`'s own types, or a base data class. Everything else is refused.

`tblib.Traceback` is admitted by class, so `find_class` alone does not vet its
contents. Its `as_traceback()` rebuilds frame objects from child-controlled
attributes, so the object's shape is checked before that call.

### 5. The descriptor fallback: keeping the refusal

Unpickling an exception drags its whole state along, and an exception's state
routinely holds objects this predicate cannot admit. `httpx.ConnectError` carries
the `httpx.Request` it failed on; a `FileNotFoundError` raised by application
code may carry a `pathlib.Path`; an application exception may carry an
application object. Admitting those would mean admitting essentially any type,
which is the fail-open posture this channel exists to avoid.

Refusing them outright is worse, though: the caller then sees
`RestrictedUnpicklingError` where it should see *which rule refused the call*,
and a sandbox that cannot report its own refusal has lost its point.

So the child sends the exception **twice**:

- the **rich form**, the pickled `(exception, traceback)` pair, as before;
- the **descriptor form**, `(module, qualname, message, denials)` — strings and
  a list of strings — plus the same traceback.

The parent tries the rich form under the predicate above. If the guard refuses
it, the parent falls back to the descriptor, resolves the class from
`sys.modules` exactly as `find_class` does (never importing), and instantiates it
through `__new__` — an exception's `__init__` signature is its own business, and
replaying it with a single argument fails on any class taking more.

The descriptor payload carries primitives only, so its predicate admits `tblib`
and nothing else.

**What a caller keeps and loses on the fallback path:**

```python
try:
    fetch_webpage(url)
except httpx.ConnectError as e:  # the class is preserved
    str(e)                       # the message is preserved
    sandbox_denials(e)           # the denials are preserved
    e.__traceback__              # the sandbox frames are preserved
    e.request.url                # AttributeError: the state is NOT preserved
```

The attributes survive whenever the rich form is admissible, which covers an
exception carrying no state, or state made only of the base data classes. They
are lost exactly when the guard would otherwise have refused the exception
entirely.

Two failures stop being fatal along the way. An exception the child cannot
pickle at all no longer sinks the reply, and a class the parent never imported
no longer raises: the refusal is reported through `SandBoxProtocolError`,
prefixed with the original `module.qualname`, rather than being lost.

## The `remote-result-guard` profile key

The result-channel denylist is the one **risky** layer (fail-open, and it can in
principle reject an exotic legitimate return). It is controlled by a profile
key:

```
remote-result-guard=true    # default: the result denylist is active
remote-result-guard=false   # disable the result denylist only
```

Turning it off disables **only** that denylist. The opcode prescan, the DoS
budgets, the exception-channel guard, and the `tblib` shape check stay active.
With it off, the result channel has no protection against the `__reduce__`
vector (the opcode allowlist does not see it), so leave it on unless a real
regression forces otherwise.

The result channel also accepts an opt-in structural profile:

```
remote-result-mode=objects     # default; supports application-defined classes
remote-result-mode=data-only   # permits exact primitive types and containers
```

`data-only` rejects object reconstruction opcodes during the prescan, before
unpickling, then checks the resulting graph contains only `None`, booleans,
numbers, strings, bytes, bytearrays, and built-in list, tuple, dict, set, or
frozenset containers. Cycles and subclasses are refused. The mode remains in
force even if `remote-result-guard=false`; that switch controls only the
denylist in `objects` mode.

Learning mode inspects the emitted pickle opcodes without unpickling. It writes
`remote-result-mode=data-only` when observed results use only data opcodes. If
any observed result needs class reconstruction, it writes `objects` with a
warning in the generated profile because class-defined reconstruction methods
can execute in the parent process. Repeated observations collapse to one rule.
If a later learning run observes objects while the active mode is `data-only`,
it comments the previous rule with the enrichment date and adds the new mode in
the dated learning block. An active `objects` mode is not tightened based only
on one run that happened to return primitives. Review the generated profile;
learning only describes the results exercised by that run.

## Portability

Sites that depend on CPython internals carry a `# CPYTHON-COMPAT:` marker
(`rg CPYTHON-COMPAT` to find them): the opcode alphabet (which can grow between
versions — a corpus test reasserts that a representative sample stays within the
allowlist, so a version bump reddens CI instead of breaking production), the
in-house qualified-name resolution (replacing the private `pickle._getattribute`),
and the pinned wire protocol constant (used on both ends instead of
`HIGHEST_PROTOCOL`, so the alphabet does not drift with the interpreter and the
two ends stay compatible across container backends). Supported range: CPython
3.11 to 3.14.

## Limits

- The result denylist is fail-open and not exhaustive; an unlisted dangerous
  module passes. See layer 3.
- An exception whose `__reduce__` rebuilds through a *function* (rather than a
  class) is refused on the exception channel; the descriptor fallback still
  delivers its class, message and denials, without its state.
- An exception that crosses on the fallback path arrives without its attributes.
  See layer 5.
- `__cause__` and `__context__` do not survive the transport, on either path.
  That is plain pickle behaviour and predates this guard; `sandbox_denials`
  exists because of it.
- This guard protects the parent's deserialization only. Arbitrary Python in the
  child can still reach native code by other routes; the OS-level sandbox remains
  the real barrier. See [weaknesses](weaknesses.md).
