# Security limits and residual risks

## Scope

The Python layer (`py-sandbox`) intercepts supported Python APIs. It is a policy
and visibility layer, not an isolation boundary against a determined attacker.
Use an OS provider when the threat model includes hostile code that can use
native extensions or direct system calls. The provider comparison describes
what each OS mechanism can enforce and its prerequisites.

## Python-layer limits

- **Introspection can reach guard internals.** Python code can inspect wrappers,
  original callables, rules, or the armed state. The
  [Python-layer assessment](audit-python-security.md) separates demonstrated
  paths from source-based reasoning and links each finding to regression tests.
- **Native code can bypass Python wrappers.** `ctypes`, compiled extensions,
  and direct system calls can access capabilities the Python layer does not
  mediate. Secrets already present in the process memory are not protected from
  such code.
- **Some API edge cases remain.** For example, `dir_fd` checks resolve a path
  before the kernel operation; a concurrent rename can create a
  time-of-check/time-of-use race. A file descriptor already held by the code is
  itself a capability.
- **Windows: the Proactor event loop bypasses the socket methods.** asyncio's default loop on Windows calls
  `_overlapped.ConnectEx`, `WSASendTo` and `AcceptEx` on the socket handle, which the socket guard does not
  wrap: the destination of an asyncio connection or datagram is not judged by the `net=` rules there.
- **The daemon's own modules escape the import rules outside a call.** In partial mode, the sandbox process runs
  an HTTP server (uvicorn, fastapi) after the guards are active, and the modules it imports for itself stay
  loaded. While the user's code runs (the import of its module, `init_fn`, each call of a `@sandbox` function and
  the tasks it awaits), every import is judged on `python-import=` alone, loaded or not: `__import__`,
  `importlib.import_module` and `importlib.__import__` are wrapped for that. Code that runs outside such a call is
  not judged that way: a thread the user's code starts (it does not inherit the call's context), a finalizer, an
  `atexit` function, or the `__reduce__` of a returned object, run while the daemon serializes the result. There,
  the modules the daemon loaded for itself are importable without a rule: `__future__`, `_hashlib`, `_hmac`,
  `_multiprocessing`, `_queue`, `_socket`, `_thread`, `abc`, `annotated_doc`, `annotated_types`, `annotationlib`, `anyio`, `array`,
  `ast`, `asyncio`, `base64`, `binascii`, `click`, `codecs`, `collections`, `colorsys`, `concurrent`,
  `configparser`, `contextlib`, `contextvars`, `copy`, `copyreg`, `dataclasses`, `datetime`, `decimal`, `email`,
  `enum`, `errno`, `fastapi`, `fractions`, `functools`, `gettext`, `h11`, `hashlib`, `heapq`, `hmac`, `html`,
  `http`, `importlib`, `inspect`, `io`, `ipaddress`, `itertools`, `json`, `keyword`, `locale`, `logging`, `math`,
  `mimetypes`, `multiprocessing`, `operator`, `os`, `pathlib`, `pickle`, `platform`, `pydantic`, `pydantic_core`,
  `queue`, `random`, `re`, `reprlib`, `secrets`, `selectors`, `shlex`, `signal`, `socket`, `socketserver`, `ssl`,
  `starlette`, `stat`, `struct`, `tempfile`, `textwrap`, `threading`, `time`, `traceback`, `types`, `typing`,
  `typing_extensions`, `typing_inspection`, `urllib`, `uuid`, `uvicorn`, `weakref`, `zoneinfo`. The imports that
  importlib's bootstrap makes for itself are not judged either, nor the relative imports a kept package such as
  `asyncio` makes of its own submodules. Code that runs with the globals of one of those modules passes for it, and
  that takes no grant: `type(lambda: 0)(code, module.__dict__)()` builds such a function without `exec` or
  `compile`, so this route is open to any user code, for the modules already loaded. Importing a module is not calling
  it: the sensitive functions they hold stay behind `python-api`, and files and sockets behind their own guards.
  `tests/integration_tests/test_framework_imports.py` fails if this list grows.
- **The local transport is not an OS boundary.** A co-resident process that
  learns the daemon's local port and token may reach it. The token and random
  port raise the cost; they do not protect against an attacker who can read
  them.

## Return-value deserialization

The trusted parent must deserialize values returned by the sandbox child. The
default `remote-result-mode=data-only` accepts values only: primitive values,
built-in containers, paths, dates and time zones, decimals, fractions, UUIDs
and IP addresses, from a closed list. It
rejects applications that return custom objects. `remote-result-mode=objects`
rebuilds them behind a guard that filters known dangerous pickle gadgets, but it
is a fail-open denylist and does not prove that every gadget is blocked. See the [transport guard assessment](transport-unpickle-guard.md)
for the result and exception channel behavior.

## Additional measured findings

The development assessment also records narrower cases: `ctypes.pythonapi` is
created before the constructor patch can intercept it; a private event-loop
`KeyboardInterrupt` path can call `_thread.interrupt_main`; and enforcement can
be disarmed through the same introspection weakness. These are detailed in the
[Python-layer assessment](audit-python-security.md) and are not claims that an
OS provider is bypassed.

## Recommendations

- Keep the Python layer enabled for policy feedback and supported-API checks.
- Add an OS provider appropriate to the deployment when native or compiled code
  is within the threat model. Review its host, kernel, network, and container
  prerequisites before relying on it.
- Treat learned rules as a starting policy. Exercise representative paths and
  review the result before enforcing it.
- Keep the default `remote-result-mode=data-only` when the application can
  return values; set `remote-result-mode=objects` only for the objects it must
  return, and keep `remote-result-guard` on.
