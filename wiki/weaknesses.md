# What are the weaknesses of py-sandbox?
There are several vulnerabilities in the proposed implementation. We are perfectly aware of them. The goal is not to execute unhealthy code, but to limit the malicious uses of our application.

Here are some vulnerabilities:

  - Each function or method patch must keep a link to the original method. An advanced introspection analysis can find it and invoke it outside of the security rules.
  - All classes are available via `object().__subclasses__()` and therefore also all modules. By analyzing this, it is possible to find the rules and modify them.
  - Any compiled code can have access to the entire Python memory and therefore find all secrets. A vulnerability in a Python library using compiled code can be exploited.
  - A child process, if it has the rights to read `/proc/${PPID}/environ`, can search for tokens there. **OS-sandboxes** generally prohibit this.
  - A direct network connection to the sandbox it's possible. A secret token, a random port and a limitation of localhost network are used.

The sensitive functions that used to be reachable as soon as their module was importable (`os.system`, `os.fork`, `os.kill`, ...) are denied by default, independently of import rights. That closes a hole; it does not close the three below, all measured while building it:

  - `ctypes.pythonapi` is a `ctypes.PyDLL` instance built at import time. Using it calls no `__init__`, so it escapes the guard, even though `ctypes.CDLL` itself is patched through `__init__`.
  - The daemon's private event loop calls `_thread.interrupt_main` from its `except KeyboardInterrupt` handler around `run_forever()`, in a background thread. Its reach is narrow: CPython delivers `SIGINT` to the main thread, so this only fires on an explicit `KeyboardInterrupt` in that loop.
  - Enforcement only starts once `arm()` has been called, and that flag can be reset the same way the rules above can be found and modified: through `object().__subclasses__()`. This is not a new class of weakness, just the existing one applied to one more flag.

A call that names its file relative to an open directory (`dir_fd`) is resolved by the kernel against that directory, not the current one. `os.unlink`, `os.rmdir`, and every call going through the generic one-file wrapper (`os.remove`, `os.mkdir`, `os.chmod`, ...) now resolve the descriptor and check the real path, so `shutil.rmtree` cannot empty an `expose-ro` tree. Two families still do not:

  - `os.open(name, flags, dir_fd=fd)` applies only the `ignore` rules, so a write-mode open relative to a descriptor is not checked against `expose-ro`.
  - `os.rename`, `os.replace` and `os.link` with `src_dir_fd`/`dst_dir_fd`, and `os.symlink` with `dir_fd`, check the names as if they were relative to the current directory.

Separately from patching, the SSE transport's return channel deserializes child-produced payloads in the trusted parent. That used to be an unrestricted `pickle.loads`, a direct escape: a hostile `__reduce__` in a returned object runs code in the parent, outside the sandbox. It is filtered by a restricted unpickler (see [the transport unpickle guard](transport-unpickle-guard.md)). The exception channel is fail-closed; the result channel is a fail-open denylist, so for return values it raises the cost of a gadget rather than closing the class, and can be turned off with `remote-result-guard=false`.

None of this makes patching complete against hostile code: arbitrary Python can always call native code. The layer raises the cost of a sensitive call from non-hostile code, and makes such calls visible in learning mode. The OS-sandboxes remain the real barrier.
