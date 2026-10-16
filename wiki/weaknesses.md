# Security limits and verified residual risks

## How to read this page

This page summarizes limitations found in the current code and focused probes. Each item names whether the behavior was reproduced or established from code. A reproduced result applies to the tested configuration and environment; it does not prove that all providers or deployments behave identically.

PySandboxes combines Python API guards with an optional OS provider. Python guards mediate supported Python calls; they are not a boundary against hostile native code in the same process. `none` and `subprocess` do not add a kernel boundary. Kernel-backed providers must be evaluated separately for their platform, kernel, configuration, and exposed host resources.

Detailed evidence and attack paths are in the [Python-layer assessment](audit-python-security.md), the [`eval-*` assessment](audit-eval-security.md), and the [native and OS-boundary assessment](audit-native-guard-study.md).

## OS-provider limitations

- **QEMU `expose-ro` is writable by native guest code — reproduced.** In a QEMU guest with `py-sandbox=false`, a native write through an `expose-ro` 9p share changed a host sentinel. The QEMU mount construction does not carry the rule's write bit into a read-only export option, and the guest mount has no `ro` option. Do not rely on QEMU `expose-ro` for host-file integrity until this is fixed and retested end to end. This result is specific to the current QEMU provider path.
- **Landlock has no implicit network deny — reproduced on ABI 8.** A native loopback connection succeeded when no socket rules were configured. TCP bind/connect filtering requires explicit socket rules and a kernel with Landlock ABI 4 or later. Without that support, do not claim Landlock network confinement.
- **Landlock allowed opening `/dev/full` for writing — reproduced, impact limited.** The probe only opened the node; it did not write, and the environment lacked `/dev/kvm`, `/dev/dri`, and `/dev/fuse`. This does not establish access to those devices or a privilege escalation. Device nodes present on a deployment and their DAC permissions affect the impact.
- **Mount errors can be non-fatal — QEMU code-established; unshare reproduced for a setup failure.** QEMU's generated guest script tolerates 9p and ignore-overlay mount failures and continues. In the tested unshare ignore-overlay failure path, setup continued after warning; user-defined bind-mount failures follow a separate path and are propagated. Startup success by itself is not evidence that a requested ignore overlay took effect.
- **Landlock cannot enforce `ignore=` rules — code-established.** Its allow-rule model does not hide an otherwise reachable path. The provider warns about ignored paths; when Python guards are disabled, an `ignore=` rule is not an OS-level denial.

See [native and OS-boundary assessment](audit-native-guard-study.md) and [Landlock limits](landlock.md#limits) for details and provider-specific qualifications.

## Python API guards

Python API patching is useful for policy checks and reporting, but code in the same interpreter can reach Python objects that implement or configure those checks. The refreshed [Python-layer assessment](audit-python-security.md) separates demonstrated bypasses from source-based or conditional findings. Among the directly demonstrated cases are mutable file-guard rules and access to already-loaded modules through `sys.modules`; neither result by itself proves a kernel boundary is bypassed.

Known CPython limitations include immutable `object.__subclasses__`, an already-loaded pickle implementation, frame/global introspection, and the immutable C implementation of `pickle.Unpickler.load`. Their exact consequences depend on the guard configuration and execution path. They are documented as limitations of Python-level mediation, not as unexpected failures of the pytest suite: tests marked `xfail` are expected-failure records.

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
