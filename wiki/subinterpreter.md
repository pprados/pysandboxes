# subinterpreter (experimental)

`os-sandbox=subinterpreter` runs the sandboxed calls in an isolated subinterpreter
([PEP 734](https://peps.python.org/pep-0734/)) of the host process, with the Python
guards armed there and only there. It needs Python 3.13 or later, on Linux.

## How it works

- At `with sandboxes()`, the host creates one interpreter with the `isolated`
  configuration: its own GIL, its own `sys.modules` and builtins, no `fork()`, no
  daemon thread, and only C extensions that support several interpreters.
- The host's `sys.path` is copied into it, then `pysandboxes.remote.subinterpreter_child`
  arms the guards as `main_sandbox` does in a child process. The host is never patched:
  its `open`, `os.system` and lifecycle flags stay untouched.
- A call crosses as a pickle, like the SSE transport: `module:qualname` plus the
  arguments. The reply comes back as a frame on a pipe, and the host reads it through the
  same restricted unpickler and exception descriptor as every other provider.
- `python-sb` runs the whole program in such an interpreter.

## What it does not isolate

The interpreter shares the host process. With the Python guards walked around (compiled
code, `ctypes`, an allowed sensitive call), the sandboxed code reaches:

- the host's memory, secrets included (shown by reading `/proc/self/mem`);
- the host's open file descriptors;
- the working directory (`os.chdir` moves the host too);
- the C-level environment: `os.environ` is narrowed in the interpreter only, `putenv`
  changes the host's, and with `with sandboxes()` pure Python code gets the host's whole
  environment back by re-importing `posix` (pinned as an xfail in
  `tests/integration_tests/remote/test_subinterpreter.py`). `python-sb` is not exposed:
  it narrows the process environment before starting the interpreter;
- the process itself: `os._exit()` ends the host.

Every rule (`expose-ro`, `expose-rw`, `ignore=`, `net=`, `env=`) is enforced by the Python
guards only. With `py-sandbox=false`, nothing is enforced, and a warning says so.

A call that never returns cannot be killed: after `TIMEOUT_FOR_RPC_CALL` the caller gets an
error, the interpreter stays busy and is left behind at shutdown.

## Compatibility

Measured with the `isolated` configuration: `aiohttp`, `uvicorn`, `ssl`, `sqlite3`,
`ctypes`, `asyncio` load. `pydantic_core` (so `pydantic` and `fastapi`), `numpy`,
`netifaces` and `readline` refuse to load. The sandboxed code cannot install a signal
handler: `signal.signal()` raises `ValueError`.

Python 3.12 is refused: its `_xxsubinterpreters` cannot load `zoneinfo` in an isolated
interpreter, and `destroy()` hangs after a failed run. Python 3.11 shares one GIL between
interpreters.
