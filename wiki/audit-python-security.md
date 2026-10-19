# Python-layer security assessment

This assessment covers the runtime guards (`guard_files`, `guard_socket`,
`guard_import`, `guard_envs`, `guard_api`) and their lifecycle. Hostile code in
the same interpreter can inspect or reassign guard state, retain references,
and call native or unpatched interfaces. Python patching is not containment for
hostile bytecode.

OS protection depends on the provider. `none` and `subprocess` add no kernel
boundary. Kernel-backed providers add provider-specific controls; see
[OS providers](os-providers.md). A Python-policy bypass does not prove an OS
boundary escape.

## Evidence and scope

The named probes were reproduced in-memory during the 2026-10-16 audit; no
committed probe file exists. The task ledger records 3,689 unit tests passed,
20 skipped and 6 xfailed on Python 3.14.5, with integration tests still running
at that checkpoint. Cited tests are regression evidence for their named cases,
not proof that equivalent routes are closed.

Threat model: code executes inside the guarded interpreter after activation.
A **policy bypass** performs an operation denied by a Python rule; **denial of
service** consumes resources or disrupts execution; **host boundary escape**
accesses beyond the configured OS/process boundary. These are distinct results.

## Findings

| Finding | Control path and evidence | Result, prerequisites, limits |
|---|---|---|
| Reassign `guard_files._rules` | `pysandboxes/guard_files.py::_apply_dest_to_src_rules` uses module-global `_rules` for access decisions. In-memory probe: activate `py-sandbox=true`, `os-sandbox=none`, `learn=false`, with no file rule; from `guard_import.user_code()`, import `pysandboxes.guard_files`, assign `_rules = (FSExposeRule(secret_dir, True, ConfigLine(...)),)`, then `open(secret)`. | **Reproduced policy bypass.** A denied read becomes allowed after arbitrary Python mutates live guard state. Requires in-process module access and a writable binding. No OS boundary is enabled in this probe; a kernel provider may still constrain the file according to its mounts/rights. `tests/unit_tests/guard/test_guard_files_coverage.py` tests ordinary decisions, not hostile rebinding. |
| Retrieve a cached module without importing it | `pysandboxes/guard_import.py` judges imports through `GuardFinder`/`_judge_user_import`; mapping lookup bypasses that path. In-memory probe: import `json` in `framework_imports()`, then from `user_code()` observe `import json` refused while `sys.modules['json']` returns the module. | **Reproduced import-policy bypass.** Requires a cached entry and access to `sys`. Module availability is distinct from permission to call each capability it exposes; `guard_api` has a separate, itself bypassable patch layer. `tests/unit_tests/guard/test_guard_import.py` and `test_guard_escape_fixes.py` cover finder decisions, not this lookup. |
| Recover originals or mutate Python guard state | Python wrappers, closure cells, and module globals remain Python objects. `tests/unit_tests/test_escape_pysandbox.py` marks four expected strict xfails: `__subclasses__` traversal, access to pickle already loaded, `__globals__` introspection, and `pickle.Unpickler.load` (an immutable C method that cannot be patched). | **Open for hostile Python code.** These four xfails record expected open routes, not unexpected suite failures. The two unrelated QEMU xfail defects in URL whitespace handling and numeric mount ordering have been fixed; their tests now pass. Exact reach depends on objects available to the code. This enables policy bypass; it is a host boundary escape only if the configured process/OS boundary also fails or is absent. |
| Symlink/canonical path checks and TOCTOU | `pysandboxes/guard_files.py::_apply_dest_to_src_rules` checks a realpath-resolved path; descriptor-relative wrappers resolve `dir_fd` before checking. | Covered symlink and `dir_fd` cases are refused in `tests/unit_tests/guard/test_guard_escape_fixes.py` and `tests/unit_tests/guard/test_guard_files_coverage.py`. Check and syscall are separate, so a path or directory changed between them creates a conditional TOCTOU race. This is not a demonstrated general bypass. Kernel policy is the backstop. |
| Held or inherited file descriptors | Path wrappers cannot revoke a descriptor already opened; descriptor-relative operations have a check/use interval. | A held descriptor remains a capability even when later path access would be denied. Provider inheritance and kernel policy determine the remaining access. Do not read path-rule tests as proof of descriptor revocation. |
| Network and process operations | `pysandboxes/guard_socket.py` checks wrapped socket operations; `pysandboxes/guard_api.py` wraps registered sensitive APIs. | Named covered cases are exercised by `tests/unit_tests/guard/test_guard_socket.py` and `test_guard_api.py`. Native calls, inherited sockets, unpatched entry points, and recovered originals are outside those checks. These are Python policy bypass routes. Network namespaces/firewalling and process restrictions vary by provider; `none` and `subprocess` have no OS boundary. |
| Import policy | `pysandboxes/guard_import.py` installs a finder and judges import names. | Covered imports are refused by tests in `tests/unit_tests/guard/test_guard_import.py`; cached `sys.modules` access is the exception reproduced above. Import denial does not revoke existing references. |
| Environment and secrets | `pysandboxes/guard_envs.py` filters Python environment access; ordinary paths use file rules. | Environment behavior is exercised in `tests/unit_tests/guard/test_guard_env.py`. This does not prevent native access, memory inspection, or OS-file access beyond the configured process boundary. `/proc`, inherited descriptors, and memory exposure depend on provider configuration. |
| Learning mode | `is_learning_mode()` branches in `pysandboxes/guard_files.py`, `guard_import.py`, `guard_socket.py`, and `guard_api.py` record activity while allowing operations. | Learning mode is observation, not enforcement. Operations can have effects before the generated profile is reviewed. This is a configuration/lifecycle risk, not proof of a sandbox escape. |
| Lifecycle and signals | Activation and arming live in `pysandboxes/lifecycle.py` and `pysandboxes/sandboxes_api.py`; signal installation/restoration is process-global and main-thread-sensitive. | A probe confirmed sandbox code can install `SIG_IGN` for `SIGTERM` and resist the parent's death signal. This is a lifecycle limitation where the provider relies on that signal; it is not evidence of crossing an OS boundary. `tests/unit_tests/test_sandboxes_api_gaps.py` checks handler restoration and worker-thread behavior, not hostile signal changes. |
| Stdio and IPC | `pysandboxes/remote/catch_stdio.py` routes output; SSE transport is implemented in `pysandboxes/remote/sse_server_daemon.py` and related modules. | Captured stdio is a transport feature, not a confidentiality boundary. Same-interpreter code can inspect Python objects; a process sharing host networking may reach loopback services if it obtains credentials. `tests/unit_tests/remote/test_sandbox_daemon_stream.py` checks stream behavior. Provider network isolation and per-run tokens are separate controls. |

## Operational conclusion

Python guards provide deny-by-default policy checks for cooperative or
mistaken code. They are not a sandbox against arbitrary Python bytecode. Use a
kernel-backed provider when deliberate in-process bypass is in scope, and
verify its actual filesystem, network, process, and descriptor configuration.
`none` and `subprocess` must be treated as having no OS security boundary.
