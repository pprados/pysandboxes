# Security limits and verified residual risks

## How to read this page

This page summarizes limitations found in the current code and focused probes. Each item names whether the behavior was reproduced or established from code. A reproduced result applies to the tested configuration and environment; it does not prove that all providers or deployments behave identically.

PySandboxes combines Python API guards with an optional OS provider. Python guards mediate supported Python calls; they are not a boundary against hostile native code in the same process. `none` and `subprocess` do not add a kernel boundary. Kernel-backed providers must be evaluated separately for their platform, kernel, configuration, and exposed host resources.

Detailed evidence and attack paths are in the [Python-layer assessment](audit-python-security.md), the [`eval-*` assessment](audit-eval-security.md), and the [native and OS-boundary assessment](audit-native-guard-study.md).

## OS-provider limitations

- **Landlock cannot filter native UDP — current limitation.** Landlock denies TCP bind/connect by default when ABI v4 is available and opens only configured ports. It has no UDP network rights. The provider is unavailable below ABI v4 rather than running without the default TCP restriction.
- **Landlock allowed opening `/dev/full` for writing — reproduced, impact limited.** The probe only opened the node; it did not write, and the environment lacked `/dev/kvm`, `/dev/dri`, and `/dev/fuse`. This does not establish access to those devices or a privilege escalation. Device nodes present on a deployment and their DAC permissions affect the impact.
- **Mount errors can be non-fatal — QEMU code-established; unshare reproduced for a setup failure.** QEMU's generated guest script tolerates 9p and ignore-overlay mount failures and continues. In the tested unshare ignore-overlay failure path, setup continued after warning; user-defined bind-mount failures follow a separate path and are propagated. Startup success by itself is not evidence that a requested ignore overlay took effect.
- **DNS stays open as an exfiltration channel — code-established, not reproduced.** The providers that give the sandbox its own network namespace (`unshare`, `bwrap`, `firejail`, `qemu`) build their kernel filter with `rule_to_netfilter` (`pysandboxes/netfilter.py`), which always accepts new UDP packets to port 53 of each DNS server of the namespace, whatever the `net=` rules say. The resolver is the slirp4netns one (`10.0.2.3`) for `unshare`, `bwrap` and `qemu`, and `unshare` may add the host's upstream servers. The filter does not restrict which names that resolver is asked about. If it forwards to an upstream resolver, as slirp4netns is designed to do (this forwarding was not reproduced), code that encodes data in query names (`<data>.attacker.example`) can send it out through the recursion, even with every `net=` rule denied. The name pinning of [DNS](dns.md) governs what the Python layer resolves; it does not stop native code, a child process or a direct UDP datagram from querying port 53. With `landlock` the same holds for a stronger reason, since it has no UDP right (see above), and `none` and `subprocess` add no network boundary. The channel is narrow in bandwidth and noisy, but nothing in the filter limits or logs it. Treat a profile that denies all outbound traffic as still permitting low-rate DNS exfiltration, and, where this is in the threat model, route the namespace through a resolver that answers only the names of the `net=ALLOW` rules.
- **Landlock cannot enforce `ignore=` rules — code-established.** Its allow-rule model does not hide an otherwise reachable path. The provider warns about ignored paths; when Python guards are disabled, an `ignore=` rule is not an OS-level denial.

See [native and OS-boundary assessment](audit-native-guard-study.md) and [Landlock limits](landlock.md#limits) for details and provider-specific qualifications.

## Python API guards

Python API patching is useful for policy checks and reporting, but code in the same interpreter can reach Python objects that implement or configure those checks. The refreshed [Python-layer assessment](audit-python-security.md) separates demonstrated bypasses from source-based or conditional findings. Among the directly demonstrated cases are mutable file-guard rules and access to already-loaded modules through `sys.modules`; neither result by itself proves a kernel boundary is bypassed.

Known CPython limitations include immutable `object.__subclasses__`, an already-loaded pickle implementation, frame/global introspection, and the immutable C implementation of `pickle.Unpickler.load`. Their exact consequences depend on the guard configuration and execution path. They are documented as limitations of Python-level mediation, not as unexpected failures of the pytest suite: tests marked `xfail` are expected-failure records.

**Modules the daemon imports for itself stay importable without a rule — code-established, covered by an integration test.** The sandbox daemon starts its HTTP server with the guards armed, and arming evicts `sys.modules`, so the server's own imports go through the import guard again. `guard_import.framework_imports()` lets the daemon import them without charging the profile, records each top-level name, and keeps allowing it afterwards, because the server imports submodules lazily, per request. Sandboxed code that imports one of these names is then allowed without a `python-import` rule. This is the same condition as the `sys.modules` case above: availability of a module is not a right to call its sensitive functions, which `guard_api` still judges. The set, as the integration test `tests/integration_tests/test_framework_imports.py` pins it (the union over Python 3.11 to 3.14, since which private companion module is loaded afresh depends on what the interpreter already loaded at startup), is:

`__future__`, `_hashlib`, `_hmac`, `_multiprocessing`, `_queue`, `_socket`, `_thread`, `abc`, `annotated_doc`, `annotated_types`, `annotationlib`, `anyio`, `array`, `ast`, `asyncio`, `base64`, `binascii`, `click`, `codecs`, `collections`, `colorsys`, `concurrent`, `configparser`, `contextlib`, `contextvars`, `copy`, `copyreg`, `dataclasses`, `datetime`, `decimal`, `email`, `enum`, `errno`, `fastapi`, `fractions`, `functools`, `gettext`, `h11`, `hashlib`, `heapq`, `hmac`, `html`, `http`, `importlib`, `inspect`, `io`, `ipaddress`, `itertools`, `json`, `keyword`, `locale`, `logging`, `math`, `mimetypes`, `multiprocessing`, `operator`, `os`, `pathlib`, `pickle`, `platform`, `pydantic`, `pydantic_core`, `pysandboxes`, `queue`, `random`, `re`, `reprlib`, `secrets`, `selectors`, `shlex`, `signal`, `socket`, `socketserver`, `ssl`, `starlette`, `stat`, `struct`, `tempfile`, `textwrap`, `threading`, `time`, `traceback`, `types`, `typing`, `typing_extensions`, `typing_inspection`, `urllib`, `uuid`, `uvicorn`, `weakref`, `zoneinfo`; on Windows also `_ctypes`, `_winapi`, `ctypes`, `msvcrt`, `nt`.

The test fails when the set grows, so this list and the test move together.

Native extensions, `ctypes`, and direct system calls are outside Python wrapper mediation. If such code is within the threat model, use an OS boundary appropriate to the deployment and account for its provider-specific residuals above.

## `eval-*` source execution

The `eval-*` feature parses and checks source strings, rewrites operations, and applies runtime restrictions. Its guarantees and remaining cases are independent of the ordinary Python import/API guards. Consult the current [`eval-*` assessment](audit-eval-security.md) for the parser and runtime boundary, including the scope and prerequisites of any demonstrated issue. Do not infer that an expression is safe solely because `__builtins__` is empty.

## Remote result and exception handling

Remote execution returns serialized results to the trusted parent. Keep `remote-result-mode=data-only` when the application can use the closed supported value set. The optional objects mode uses a restricted reconstruction path, but custom-object support expands the parent-side deserialization surface; see the [transport unpickle guard assessment](transport-unpickle-guard.md) for the result and exception channels.

The exception channel also deserves a separate trust decision: the parent reconstructs exception types that are available in the parent process. The audit documents the conditional side-effect risk for a matching preloaded exception class. This is not evidence that an arbitrary child can import an arbitrary class into the parent.

## Operational guidance

- Use `none` or `subprocess` only when the absence of a kernel boundary is acceptable.
- For native-code threats, select and test a kernel-backed provider on the target host. Confirm effective mounts, network policy, and device exposure rather than relying only on successful startup.
- Keep Python API guards enabled for policy enforcement and useful denials, while treating them as one layer of defense.
- Prefer `remote-result-mode=data-only`; enable object reconstruction only when required by the application.
- Treat any claim as configuration-specific. Re-run probes when changing providers, kernel, guest image, or exposed paths.
